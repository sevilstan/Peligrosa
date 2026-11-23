"""Telegram foundation tests: users, gallery service, slider, avatars.

No network and no bot token (see tests/telegram_harness.py). Tests that need
PostgreSQL use the run_db fixture (skipped without TEST_DATABASE_URL).
"""

import asyncio
from pathlib import Path

import pytest
from aiogram.types import Message

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
from app.telegram.avatars import AvatarProvider
from app.telegram.bot import build_bot, build_dispatcher
from app.telegram.chat_utils import split_text
from app.telegram.texts import TEXTS, all_labels, t
from sqlalchemy import select

from tests.telegram_harness import (
    PNG,
    Harness,
    add_characters,
    callback_update,
    message_update,
    user_count,
)


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
    assert t("tr", "menu_chats") != t("en", "menu_chats")
    assert all_labels("menu_chats") == {t("en", "menu_chats"), t("tr", "menu_chats")}


def _data(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row]


def test_slider_wraps_around_and_shows_counter():
    chars = [GalleryCharacter("a", "A", "d")]

    first = keyboards.slider_keyboard(GalleryPage(chars, 0, 3), "en")
    middle = keyboards.slider_keyboard(GalleryPage(chars, 1, 3), "en")
    last = keyboards.slider_keyboard(GalleryPage(chars, 2, 3), "en")

    assert _data(first) == ["gallery:2", "noop", "gallery:1", "open:a"]
    assert _data(middle) == ["gallery:0", "noop", "gallery:2", "open:a"]
    assert _data(last) == ["gallery:1", "noop", "gallery:0", "open:a"]
    assert first.inline_keyboard[0][1].text == "1/3"


def test_single_character_has_no_arrows():
    markup = keyboards.slider_keyboard(GalleryPage([GalleryCharacter("a", "A", "d")], 0, 1), "en")
    assert _data(markup) == ["open:a"]


def test_callback_data_never_exceeds_telegram_limit():
    long_one = GalleryCharacter("x" * 80, "Long", "d")
    markup = keyboards.slider_keyboard(GalleryPage([long_one], 0, 1), "en")

    assert _data(markup) == []
    assert keyboards.new_chat_keyboard(long_one, "en") is None


def test_split_text_keeps_parts_within_the_limit():
    text = ("word " * 50 + "\n\n") * 6

    parts = split_text(text, limit=100)

    assert all(0 < len(p) <= 100 for p in parts)
    assert " ".join(" ".join(parts).split()) == " ".join(text.split())
    assert split_text("short") == ["short"]
    assert len(split_text("x" * 250, limit=100)) == 3  # no boundary: hard cut


# ------------------------------------------------------------- avatars


def test_local_avatar_beats_avatar_url_and_is_sent_as_file(tmp_path):
    (tmp_path / "amy.png").write_bytes(PNG)
    provider = AvatarProvider(tmp_path)

    source = provider.resolve("amy", "https://example.test/a.png")

    assert source.key.startswith("file:amy.png:")
    assert type(source.media).__name__ == "FSInputFile"


def test_avatar_url_must_be_https_and_slug_cannot_escape_the_folder(tmp_path):
    (tmp_path.parent / "secret.png").write_bytes(PNG)
    provider = AvatarProvider(tmp_path)

    assert provider.resolve("amy", "https://example.test/a.png").media == "https://example.test/a.png"
    assert provider.resolve("amy", "http://example.test/a.png") is None
    assert provider.resolve("amy", "file:///etc/passwd") is None
    assert provider.resolve("amy", None) is None
    assert provider.resolve("../secret", None) is None


def test_file_id_is_reused_until_forgotten_or_file_changes(tmp_path):
    import os
    from aiogram.types import Chat, PhotoSize

    path = tmp_path / "amy.png"
    path.write_bytes(PNG)
    provider = AvatarProvider(tmp_path)
    sent = Message(
        message_id=1, date=0, chat=Chat(id=1, type="private"),
        photo=[PhotoSize(file_id="FID", file_unique_id="u", width=1, height=1)],
    )

    source = provider.resolve("amy", None)
    provider.remember(source, sent)
    assert provider.resolve("amy", None).media == "FID"

    os.utime(path, ns=(1, 1))  # picture replaced: old file_id is stale
    assert type(provider.resolve("amy", None).media).__name__ == "FSInputFile"

    provider.remember(provider.resolve("amy", None), sent)
    provider.forget(provider.resolve("amy", None))
    assert type(provider.resolve("amy", None).media).__name__ == "FSInputFile"


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
            page = await CharacterGalleryService(s, page_size=10).get_page(0)

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
            page = await CharacterGalleryService(s, CharacterDefinitionLoader(tmp_path), page_size=10).get_page(0)

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




def test_gallery_is_a_slider_with_one_character_per_page(run_db):
    async def scenario(maker):
        await add_characters(maker, [("A", "a", 0, True), ("B", "b", 1, True)])
        async with maker() as s:
            page = await CharacterGalleryService(s).get_page(1)

        assert [c.slug for c in page.characters] == ["b"]
        assert page.total_pages == 2

    run_db(scenario)


# ------------------------------------------------- slider flows (bot)


def test_start_registers_user_shows_menu_and_first_slide(run_db, tmp_path):
    async def scenario(maker):
        await add_characters(maker, [("Elena", "elena", 0, True), ("Natalie", "natalie", 1, True)])
        bot = Harness(maker, tmp_path)

        await bot.send(message_update("/start", user_id=555, first="Ada"))

        welcome, slide = bot.session.named("SendMessage")
        assert "Ada" in welcome["text"]
        menu = welcome["reply_markup"]["keyboard"][0]
        assert [b["text"] for b in menu] == [t("en", "menu_characters"), t("en", "menu_chats")]
        assert "Elena" in slide["text"] and "Natalie" not in slide["text"]
        assert bot.callback_data() == ["gallery:1", "noop", "gallery:1", "open:elena"]

        async with maker() as s:
            user = (await s.execute(select(User).where(User.telegram_id == 555))).scalar_one()
        assert user.display_name == "Ada"

    run_db(scenario)


def test_slide_with_a_local_picture_is_sent_as_a_photo_then_reused(run_db, tmp_path):
    (tmp_path / "elena.png").write_bytes(PNG)

    async def scenario(maker):
        await add_characters(maker, [("Elena", "elena", 0, True)])
        bot = Harness(maker, tmp_path)

        await bot.send(message_update("/characters"))
        await bot.send(message_update("/characters"))

        photos = bot.session.named("SendPhoto")
        assert len(photos) == 2
        assert "<b>Elena</b>" in photos[0]["caption"]
        assert type(photos[0]["photo"]).__name__ == "FSInputFile"
        assert photos[1]["photo"] == "tg-file-id"  # second time: no re-upload

    run_db(scenario)


def test_avatar_url_is_used_when_there_is_no_local_picture(run_db, tmp_path):
    async def scenario(maker):
        await add_characters(maker, [("Elena", "elena", 0, True)], avatar_url="https://example.test/e.jpg")
        bot = Harness(maker, tmp_path)

        await bot.send(message_update("/characters"))

        assert bot.session.named("SendPhoto")[0]["photo"] == "https://example.test/e.jpg"

    run_db(scenario)


def test_unusable_picture_falls_back_to_a_text_card(run_db, tmp_path):
    async def scenario(maker):
        await add_characters(maker, [("Elena", "elena", 0, True)], avatar_url="https://example.test/e.jpg")
        bot = Harness(maker, tmp_path)
        bot.session.photo_error = "Bad Request: wrong file identifier/HTTP URL specified"

        await bot.send(message_update("/characters"))

        assert "Elena" in bot.session.named("SendMessage")[0]["text"]
        assert bot.callback_data()[-1] == "open:elena"

    run_db(scenario)


def test_arrows_edit_text_slides_in_place(run_db, tmp_path):
    async def scenario(maker):
        await add_characters(maker, [("Amy", "amy", 0, True), ("Bob", "bob", 1, True)])
        bot = Harness(maker, tmp_path)

        await bot.send(callback_update("gallery:1"))

        edited = bot.session.named("EditMessageText")
        assert len(edited) == 1 and "Bob" in edited[0]["text"]
        assert bot.session.named("AnswerCallbackQuery")
        assert "DeleteMessage" not in bot.session.names()

    run_db(scenario)


def test_arrows_edit_photo_slides_with_edit_media(run_db, tmp_path):
    (tmp_path / "amy.png").write_bytes(PNG)
    (tmp_path / "bob.png").write_bytes(PNG)

    async def scenario(maker):
        await add_characters(maker, [("Amy", "amy", 0, True), ("Bob", "bob", 1, True)])
        bot = Harness(maker, tmp_path)

        await bot.send(callback_update("gallery:1", has_photo=True))

        media = bot.session.named("EditMessageMedia")
        assert len(media) == 1 and "Bob" in media[0]["media"]["caption"]
        assert "SendMessage" not in bot.session.names()

    run_db(scenario)


def test_switching_between_photo_and_text_slides_sends_then_deletes(run_db, tmp_path):
    (tmp_path / "bob.png").write_bytes(PNG)  # Amy has no picture, Bob has

    async def scenario(maker):
        await add_characters(maker, [("Amy", "amy", 0, True), ("Bob", "bob", 1, True)])
        bot = Harness(maker, tmp_path)

        # text slide (Amy) -> photo slide (Bob)
        await bot.send(callback_update("gallery:1", has_photo=False))
        assert bot.session.names()[:2] == ["SendPhoto", "DeleteMessage"]

        bot.session.calls.clear()
        # photo slide (Bob) -> text slide (Amy)
        await bot.send(callback_update("gallery:0", has_photo=True))
        assert bot.session.names()[:2] == ["SendMessage", "DeleteMessage"]
        assert "Amy" in bot.session.named("SendMessage")[0]["text"]

    run_db(scenario)


def test_not_modified_edit_is_swallowed_and_callback_answered(run_db, tmp_path):
    async def scenario(maker):
        await add_characters(maker, [("A", "a", 0, True)])
        bot = Harness(maker, tmp_path)
        bot.session.edit_text_error = "Bad Request: message is not modified: same content"

        await bot.send(callback_update("gallery:0"))

        assert bot.session.named("AnswerCallbackQuery")

    run_db(scenario)


def test_hostile_page_numbers_do_not_crash(run_db, tmp_path):
    async def scenario(maker):
        await add_characters(maker, [("A", "a", 0, True)])
        bot = Harness(maker, tmp_path)

        for data in ("gallery:99999999999999999999", "gallery:-1", "gallery:abc", "gallery:", "noop"):
            await bot.send(callback_update(data))

        assert len(bot.session.named("AnswerCallbackQuery")) == 5

    run_db(scenario)


def test_slide_escapes_html_in_name_and_description(run_db, tmp_path):
    async def scenario(maker):
        async with maker() as s:
            s.add(Character(name="<i>X</i>", slug="x", description="a <u>b</u> & c",
                            personality="p", system_prompt="s"))
            await s.commit()
        bot = Harness(maker, tmp_path)

        await bot.send(message_update("/characters"))

        text = bot.session.named("SendMessage")[0]["text"]
        assert "&lt;i&gt;X&lt;/i&gt;" in text
        assert "&lt;u&gt;b&lt;/u&gt; &amp; c" in text
        assert "<i>" not in text and "<u>" not in text

    run_db(scenario)


def test_ui_language_follows_the_telegram_language(run_db, tmp_path):
    async def scenario(maker):
        bot = Harness(maker, tmp_path)

        await bot.send(message_update("/characters", lang="tr"))

        assert bot.texts() == [t("tr", "gallery_empty")]

    run_db(scenario)


@pytest.mark.parametrize(
    "payload",
    [
        message_update("/start", chat_type="group"),
        message_update("/start", chat_type="supergroup"),
        message_update("/start", is_bot=True),
    ],
)
def test_non_private_and_bot_updates_are_ignored(run_db, tmp_path, payload):
    async def scenario(maker):
        bot = Harness(maker, tmp_path)
        await bot.send(payload)

        assert bot.session.calls == []
        assert await user_count(maker) == 0

    run_db(scenario)


def test_deactivated_user_gets_no_reply(run_db, tmp_path):
    async def scenario(maker):
        async with maker() as s:
            await TelegramUserService(s).get_or_create(77, "Ada")
            user = (await s.execute(select(User).where(User.telegram_id == 77))).scalar_one()
            user.is_active = False
            await s.commit()
        bot = Harness(maker, tmp_path)

        await bot.send(message_update("/start", user_id=77))
        await bot.send(callback_update("gallery:0", user_id=77))
        await bot.send(message_update("hello", user_id=77))

        assert bot.session.calls == []

    run_db(scenario)
