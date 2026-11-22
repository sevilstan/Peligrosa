"""Telegram foundation tests.

No network and no bot token: the aiogram HTTP session is replaced by a fake
that records every API call. Tests that need PostgreSQL use the run_db
fixture (skipped without TEST_DATABASE_URL).
"""

import asyncio
import time
from pathlib import Path

import pytest
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import AnswerCallbackQuery, EditMessageText, SendMessage
from aiogram.types import Chat, Message, Update
from sqlalchemy import func, select

from app.models import Character, User
from app.services.character_definition_loader import CharacterDefinitionLoader
from app.services.character_gallery_service import (
    CharacterGalleryService,
    GalleryCharacter,
    GalleryPage,
)
from app.services.telegram_user_service import (
    TelegramUserService,
    build_display_name,
    normalize_language_code,
)
from app.telegram import keyboards
from app.telegram.bot import build_bot, build_dispatcher
from app.telegram.texts import TEXTS, t

# ---------------------------------------------------------------- fakes


class FakeSession(BaseSession):
    """Records API calls instead of talking to Telegram."""

    def __init__(self):
        super().__init__()
        self.calls: list[tuple[str, dict]] = []
        self.edit_error: str | None = None

    async def make_request(self, bot, method, timeout=None):
        data = method.model_dump(exclude_none=True)
        self.calls.append((type(method).__name__, data))

        if isinstance(method, EditMessageText) and self.edit_error:
            raise TelegramBadRequest(method=method, message=self.edit_error)
        if isinstance(method, (SendMessage, EditMessageText)):
            return Message(
                message_id=500,
                date=int(time.time()),
                chat=Chat(id=data.get("chat_id", 1), type="private"),
            )
        return True

    async def close(self):
        pass

    async def stream_content(self, *args, **kwargs):  # pragma: no cover
        yield b""

    def named(self, name):
        return [data for call, data in self.calls if call == name]


def _from(user_id, is_bot, first, lang):
    return {
        "id": user_id,
        "is_bot": is_bot,
        "first_name": first,
        "language_code": lang,
    }


def message_update(text, *, user_id=1001, chat_type="private", is_bot=False, first="Ada", lang="en"):
    return {
        "update_id": 1,
        "message": {
            "message_id": 10,
            "date": int(time.time()),
            "chat": {"id": user_id, "type": chat_type},
            "from": _from(user_id, is_bot, first, lang),
            "text": text,
        },
    }


def callback_update(data, *, user_id=1001, first="Ada", lang="en"):
    return {
        "update_id": 2,
        "callback_query": {
            "id": "cb1",
            "chat_instance": "ci",
            "from": _from(user_id, False, first, lang),
            "data": data,
            "message": {
                "message_id": 20,
                "date": int(time.time()),
                "chat": {"id": user_id, "type": "private"},
            },
        },
    }


class Harness:
    def __init__(self, maker):
        self.maker = maker
        self.session = FakeSession()
        self.bot = Bot(token="123456:TEST", session=self.session)
        self.dispatcher = build_dispatcher(maker)

    async def send(self, payload):
        update = Update.model_validate(payload, context={"bot": self.bot})
        await self.dispatcher.feed_update(self.bot, update)

    def buttons(self, call_name="SendMessage", index=-1):
        markup = self.session.named(call_name)[index]["reply_markup"]
        return [b for row in markup["inline_keyboard"] for b in row]


async def add_characters(maker, specs):
    async with maker() as session:
        for name, slug, sort_order, is_active in specs:
            session.add(
                Character(
                    name=name,
                    slug=slug,
                    description=f"About {name}",
                    personality="p",
                    system_prompt="s",
                    sort_order=sort_order,
                    is_active=is_active,
                )
            )
        await session.commit()


async def user_count(maker):
    async with maker() as session:
        return (await session.execute(select(func.count()).select_from(User))).scalar_one()


# ------------------------------------------------------- pure unit tests


def test_language_code_is_normalized_to_a_safe_value():
    assert normalize_language_code("tr") == "tr"
    assert normalize_language_code("pt-BR") == "pt"
    assert normalize_language_code("EN_us") == "en"
    assert normalize_language_code(None) == "en"
    assert normalize_language_code("") == "en"
    assert normalize_language_code("12") == "en"
    assert len(normalize_language_code("zh-hans-cn")) <= 5


def test_display_name_is_joined_and_truncated():
    assert build_display_name("Ada", "Lovelace") == "Ada Lovelace"
    assert build_display_name("Ada", None) == "Ada"
    assert build_display_name(None, None) is None
    assert len(build_display_name("x" * 500)) == 100


def test_ui_texts_exist_in_every_language_with_same_keys():
    assert set(TEXTS["en"]) == set(TEXTS["tr"])
    assert t("de", "welcome", name="") == t("en", "welcome", name="")
    assert t("tr", "chat_soon") != t("en", "chat_soon")


def test_gallery_keyboard_has_navigation_only_where_it_applies():
    chars = [GalleryCharacter("a", "A", "d")]

    first = keyboards.gallery_keyboard(GalleryPage(chars, 0, 3), "en")
    middle = keyboards.gallery_keyboard(GalleryPage(chars, 1, 3), "en")
    last = keyboards.gallery_keyboard(GalleryPage(chars, 2, 3), "en")

    def data(markup):
        return [b.callback_data for row in markup.inline_keyboard for b in row]

    assert data(first) == ["char:0:a", "gallery:1"]
    assert data(middle) == ["char:1:a", "gallery:0", "gallery:2"]
    assert data(last) == ["char:2:a", "gallery:1"]


def test_callback_data_never_exceeds_telegram_limit():
    chars = [GalleryCharacter("x" * 80, "Long", "d"), GalleryCharacter("ok", "Ok", "d")]
    markup = keyboards.gallery_keyboard(GalleryPage(chars, 0, 1), "en")
    data = [b.callback_data for row in markup.inline_keyboard for b in row]

    assert data == ["char:0:ok"]
    assert all(len(d.encode()) <= 64 for d in data)


def test_bot_can_be_built_without_network():
    assert build_bot("123456:TEST") is not None


def test_dispatchers_can_be_built_repeatedly():
    # A module-level Router can only be attached to one dispatcher.
    build_dispatcher(None)
    build_dispatcher(None)


# ----------------------------------------------------------- user service


def test_get_or_create_is_idempotent_and_updates_profile(run_db):
    async def scenario(maker):
        async with maker() as s:
            first = await TelegramUserService(s).get_or_create(42, "Ada", None, "tr")
        async with maker() as s:
            second = await TelegramUserService(s).get_or_create(42, "Ada B.", None, "en-US")

        assert first.id == second.id
        assert second.display_name == "Ada B."
        assert second.language_code == "en"
        assert await user_count(maker) == 1

    run_db(scenario)


def test_simultaneous_first_updates_create_one_user(run_db):
    async def scenario(maker):
        async def one():
            async with maker() as s:
                return (await TelegramUserService(s).get_or_create(7, "Ada")).id

        ids = await asyncio.gather(*(one() for _ in range(6)))

        assert len(set(ids)) == 1
        assert await user_count(maker) == 1

    run_db(scenario)


def test_returning_user_is_never_reactivated(run_db):
    async def scenario(maker):
        async with maker() as s:
            user = await TelegramUserService(s).get_or_create(9, "Ada")
            user.is_active = False
            await s.commit()
        async with maker() as s:
            again = await TelegramUserService(s).get_or_create(9, "Ada", None, "tr")

        assert again.is_active is False

    run_db(scenario)


# -------------------------------------------------------- gallery service


def test_gallery_shows_only_active_characters_in_order(run_db):
    async def scenario(maker):
        await add_characters(
            maker,
            [("Zed", "zed", 1, True), ("Amy", "amy", 2, True), ("Hidden", "hidden", 0, False), ("Bob", "bob", 1, True)],
        )
        async with maker() as s:
            page = await CharacterGalleryService(s).get_page(0)

        assert [c.slug for c in page.characters] == ["bob", "zed", "amy"]
        assert page.total_pages == 1

    run_db(scenario)


def test_gallery_pages_and_clamps_out_of_range_pages(run_db):
    async def scenario(maker):
        await add_characters(maker, [(f"C{i}", f"c{i}", i, True) for i in range(5)])
        async with maker() as s:
            service = CharacterGalleryService(s, page_size=2)
            assert [c.slug for c in (await service.get_page(0)).characters] == ["c0", "c1"]
            last = await service.get_page(99)
            negative = await service.get_page(-5)

        assert last.page == 2 and [c.slug for c in last.characters] == ["c4"]
        assert negative.page == 0
        assert last.has_previous and not last.has_next

    run_db(scenario)


def test_gallery_prefers_yaml_and_survives_broken_yaml(run_db, tmp_path: Path):
    (tmp_path / "amy.yaml").write_text(
        "name: Amy YAML\nslug: amy\ndescription: from yaml\n", encoding="utf-8"
    )
    (tmp_path / "bob.yaml").write_text("name: [unclosed", encoding="utf-8")

    async def scenario(maker):
        await add_characters(maker, [("Amy DB", "amy", 0, True), ("Bob DB", "bob", 1, True), ("Cy DB", "cy", 2, True)])
        async with maker() as s:
            page = await CharacterGalleryService(s, CharacterDefinitionLoader(tmp_path)).get_page(0)

        by_slug = {c.slug: c for c in page.characters}
        assert (by_slug["amy"].name, by_slug["amy"].description) == ("Amy YAML", "from yaml")
        assert by_slug["bob"].name == "Bob DB"
        assert by_slug["cy"].description == "About Cy DB"

    run_db(scenario)


def test_get_character_ignores_inactive_and_unknown(run_db):
    async def scenario(maker):
        await add_characters(maker, [("On", "on", 0, True), ("Off", "off", 1, False)])
        async with maker() as s:
            service = CharacterGalleryService(s)
            assert (await service.get_character("on")).name == "On"
            assert await service.get_character("off") is None
            assert await service.get_character("nope") is None

    run_db(scenario)


# ------------------------------------------------- end-to-end bot flows


def test_start_registers_user_and_shows_gallery(run_db):
    async def scenario(maker):
        await add_characters(maker, [("Elena", "elena", 0, True), ("Natalie", "natalie", 1, True)])
        bot = Harness(maker)

        await bot.send(message_update("/start", user_id=555, first="Ada", lang="en"))

        sent = bot.session.named("SendMessage")
        assert len(sent) == 2
        assert "Ada" in sent[0]["text"]
        assert "Elena" in sent[1]["text"] and "Natalie" in sent[1]["text"]
        assert [b["callback_data"] for b in bot.buttons()] == ["char:0:elena", "char:0:natalie"]

        async with maker() as s:
            user = (await s.execute(select(User).where(User.telegram_id == 555))).scalar_one()
        assert user.display_name == "Ada"

    run_db(scenario)


def test_ui_language_follows_the_telegram_language(run_db):
    async def scenario(maker):
        await add_characters(maker, [("Elena", "elena", 0, True)])
        bot = Harness(maker)

        await bot.send(message_update("/characters", lang="tr"))

        assert "Karakterler" in bot.session.named("SendMessage")[0]["text"]

    run_db(scenario)


def test_gallery_list_escapes_html_in_names_and_descriptions(run_db):
    async def scenario(maker):
        async with maker() as s:
            s.add(Character(name="<i>X</i>", slug="x", description="a <u>b</u> & c",
                            personality="p", system_prompt="s"))
            await s.commit()
        bot = Harness(maker)

        await bot.send(message_update("/characters"))

        text = bot.session.named("SendMessage")[0]["text"]
        assert "&lt;i&gt;X&lt;/i&gt;" in text
        assert "&lt;u&gt;b&lt;/u&gt; &amp; c" in text
        assert "<i>" not in text and "<u>" not in text

    run_db(scenario)


def test_empty_gallery_says_so(run_db):
    async def scenario(maker):
        bot = Harness(maker)
        await bot.send(message_update("/characters"))

        sent = bot.session.named("SendMessage")[0]
        assert sent["text"] == t("en", "gallery_empty")
        assert "reply_markup" not in sent

    run_db(scenario)


@pytest.mark.parametrize(
    "payload",
    [
        message_update("/start", chat_type="group"),
        message_update("/start", chat_type="supergroup"),
        message_update("/start", is_bot=True),
    ],
)
def test_non_private_and_bot_updates_are_ignored(run_db, payload):
    async def scenario(maker):
        bot = Harness(maker)
        await bot.send(payload)

        assert bot.session.calls == []
        assert await user_count(maker) == 0

    run_db(scenario)


def test_deactivated_user_gets_no_reply(run_db):
    async def scenario(maker):
        async with maker() as s:
            await TelegramUserService(s).get_or_create(77, "Ada")
            user = (await s.execute(select(User).where(User.telegram_id == 77))).scalar_one()
            user.is_active = False
            await s.commit()
        bot = Harness(maker)

        await bot.send(message_update("/start", user_id=77))
        await bot.send(callback_update("gallery:0", user_id=77))

        assert bot.session.calls == []

    run_db(scenario)


def test_gallery_page_button_edits_the_message(run_db):
    async def scenario(maker):
        await add_characters(maker, [(f"C{i}", f"c{i}", i, True) for i in range(8)])
        bot = Harness(maker)

        await bot.send(callback_update("gallery:1"))

        edited = bot.session.named("EditMessageText")
        assert len(edited) == 1
        assert "(2/2)" in edited[0]["text"]
        assert "C6" in edited[0]["text"] and "C0" not in edited[0]["text"]
        assert bot.session.named("AnswerCallbackQuery")

    run_db(scenario)


def test_hostile_page_numbers_do_not_crash(run_db):
    async def scenario(maker):
        await add_characters(maker, [("A", "a", 0, True)])
        bot = Harness(maker)

        for data in ("gallery:99999999999999999999", "gallery:-1", "gallery:abc", "gallery:"):
            await bot.send(callback_update(data))

        assert len(bot.session.named("EditMessageText")) == 4

    run_db(scenario)


def test_not_modified_edit_is_swallowed_and_callback_answered(run_db):
    async def scenario(maker):
        await add_characters(maker, [("A", "a", 0, True)])
        bot = Harness(maker)
        bot.session.edit_error = "Bad Request: message is not modified: same content"

        await bot.send(callback_update("gallery:0"))

        assert bot.session.named("AnswerCallbackQuery")

    run_db(scenario)


def test_character_card_shows_escaped_details_and_back_to_the_right_page(run_db):
    async def scenario(maker):
        await add_characters(maker, [("<b>Evil</b>", "evil", 0, True)])
        bot = Harness(maker)

        await bot.send(callback_update("char:3:evil"))

        text = bot.session.named("EditMessageText")[0]["text"]
        assert "&lt;b&gt;Evil&lt;/b&gt;" in text
        assert "<b>Evil</b>" not in text
        data = [b["callback_data"] for b in bot.buttons("EditMessageText")]
        assert data == ["open:evil", "gallery:3"]

    run_db(scenario)


def test_unknown_or_inactive_character_gives_an_alert_not_a_card(run_db):
    async def scenario(maker):
        await add_characters(maker, [("Off", "off", 0, False)])
        bot = Harness(maker)

        for data in ("char:0:off", "char:0:missing", "char:0:../../etc/passwd", "char:"):
            await bot.send(callback_update(data))

        assert bot.session.named("EditMessageText") == []
        alerts = bot.session.named("AnswerCallbackQuery")
        assert len(alerts) == 4 and all(a["show_alert"] for a in alerts)

    run_db(scenario)


def test_open_button_and_plain_text_say_chat_is_coming(run_db):
    async def scenario(maker):
        bot = Harness(maker)

        await bot.send(callback_update("open:elena"))
        await bot.send(message_update("hello there", lang="tr"))

        assert bot.session.named("AnswerCallbackQuery")[0]["text"] == t("en", "chat_soon")
        # the second update carries language "tr", which refreshes the profile
        assert bot.session.named("SendMessage")[0]["text"] == t("tr", "plain_text")

    run_db(scenario)
