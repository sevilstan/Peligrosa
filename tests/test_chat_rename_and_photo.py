"""/rename, and the character's picture when a chat is opened or switched to."""

from sqlalchemy import select

from app.models import Conversation
from app.services.chat_session_service import ChatSessionService, clean_title
from app.services.telegram_user_service import TelegramUserService
from app.telegram.texts import t
from tests.telegram_harness import Harness, add_characters, callback_update, message_update
from tests.test_conversation_engine import ScriptedProvider

URL = "https://example.test/e.jpg"
TWO = [("Amy", "amy", 0, True), ("Bob", "bob", 1, True)]


async def make_user(maker, telegram_id=1001):
    async with maker() as s:
        return (await TelegramUserService(s).get_or_create(telegram_id, "Ada")).id


def service(s):
    return ChatSessionService(s, ScriptedProvider())


async def titles(maker):
    async with maker() as s:
        return [c.title for c in (await s.execute(select(Conversation))).scalars()]


# ------------------------------------------------------------ cleaning


def test_clean_title_is_one_short_printable_line():
    assert clean_title("  Movie   night ") == "Movie night"
    assert clean_title("a\nb\tc") == "a b c"
    assert clean_title("x\x00y\x07z") == "xyz"
    assert clean_title("\x00\x07  ") is None
    assert clean_title(None) is None
    assert len(clean_title("é" * 100)) == 40


# ------------------------------------------------------------ service


def test_rename_sets_clears_and_keeps_the_chat_order(run_db):
    async def scenario(maker):
        await add_characters(maker, TWO)
        uid = await make_user(maker)
        async with maker() as s:
            first = await service(s).open_character_chat(uid, "amy")
            await service(s).open_character_chat(uid, "bob")  # bob is now active

        async with maker() as s:
            renamed = await service(s).rename(uid, first.conversation_id, "Old friends")
            listing = await service(s).list_chats(uid)

        assert renamed.title == "Old friends" and renamed.label == "Old friends · Amy"
        assert renamed.name == "Amy"
        # Renaming does not touch updated_at: bob stays the active, first chat.
        assert [c.name for c in listing.items] == ["Bob", "Amy"]
        assert [c.label for c in listing.items] == ["Bob", "Old friends · Amy"]

        async with maker() as s:
            cleared = await service(s).rename(uid, first.conversation_id, "  ")
        assert cleared.title is None and cleared.label == "Amy"

    run_db(scenario)


def test_rename_only_works_on_your_own_chats(run_db):
    async def scenario(maker):
        await add_characters(maker, TWO)
        mine = await make_user(maker, 1001)
        other = await make_user(maker, 2002)
        async with maker() as s:
            chat = await service(s).open_character_chat(mine, "amy")

        async with maker() as s:
            try:
                await service(s).rename(other, chat.conversation_id, "Mine now")
            except Exception as exc:
                assert type(exc).__name__ == "ChatNotAvailableError"
            else:
                raise AssertionError("another user could rename the chat")

        assert await titles(maker) == ["Amy"]  # the default title is untouched

    run_db(scenario)


# ------------------------------------------------------------ command


def test_rename_command_titles_the_active_chat(run_db, tmp_path):
    async def scenario(maker):
        await add_characters(maker, TWO)
        bot = Harness(maker, tmp_path)
        await bot.send(callback_update("open:amy"))
        bot.session.calls.clear()

        await bot.send(message_update("/rename Movie <b>night</b>"))

        assert await titles(maker) == ["Movie <b>night</b>"]
        reply = bot.texts()[-1]
        assert reply == t("en", "rename_saved", name="Movie &lt;b&gt;night&lt;/b&gt; · Amy")

        await bot.send(message_update("/chats"))
        listed = [b["text"] for b in bot.buttons()]
        assert any("Movie <b>night</b> · Amy" in label for label in listed)

    run_db(scenario)


def test_rename_command_usage_reset_and_no_chat(run_db, tmp_path):
    async def scenario(maker):
        await add_characters(maker, TWO)
        bot = Harness(maker, tmp_path)

        await bot.send(message_update("/rename Anything"))
        assert bot.texts()[-1] == t("en", "no_active_chat")

        await bot.send(callback_update("open:amy"))
        await bot.send(message_update("/rename"))
        assert bot.texts()[-1] == t("en", "rename_usage")
        assert await titles(maker) == ["Amy"]

        await bot.send(message_update("/rename Nice"))
        await bot.send(message_update("/rename -"))
        assert bot.texts()[-1] == t("en", "rename_cleared")
        assert await titles(maker) == [None]
        await bot.send(message_update("/chats"))
        assert [b["text"].split(" · ")[0] for b in bot.buttons()][0].lstrip("● ") == "Amy"

        await bot.send(message_update("/rename \x07\x00 "))
        assert bot.texts()[-1] in (t("en", "rename_usage"), t("en", "rename_invalid"))

    run_db(scenario)


def test_a_renamed_chat_shows_its_title_in_the_divider(run_db, tmp_path):
    async def scenario(maker):
        await add_characters(maker, TWO)
        bot = Harness(maker, tmp_path)
        await bot.send(callback_update("open:amy"))
        await bot.send(message_update("/rename Late talks"))
        await bot.send(callback_update("open:bob"))
        bot.session.calls.clear()

        async with maker() as s:
            amy_chat = (
                await s.execute(select(Conversation).where(Conversation.title == "Late talks"))
            ).scalar_one()
        await bot.send(callback_update(f"chat:{amy_chat.id}"))

        assert "Late talks · Amy" in bot.texts()[-1]
        assert t("en", "chat_resumed", name="Amy") in bot.texts()[-1]

    run_db(scenario)


# ------------------------------------------------------------ photo


def test_opening_a_chat_sends_the_picture_with_the_text_as_caption(run_db, tmp_path):
    async def scenario(maker):
        await add_characters(maker, TWO, avatar_url=URL)
        bot = Harness(maker, tmp_path)

        await bot.send(callback_update("open:amy"))

        photos = bot.session.named("SendPhoto")
        assert len(photos) == 1 and photos[0]["photo"] == URL
        assert t("en", "chat_new", name="Amy") in photos[0]["caption"]
        assert "━" in photos[0]["caption"]  # the divider
        assert bot.session.named("SendMessage") == []  # one message, not two
        assert any(b["callback_data"].startswith("hopen:") for b in bot.buttons("SendPhoto"))

    run_db(scenario)


def test_new_chat_and_switching_also_show_the_picture(run_db, tmp_path):
    async def scenario(maker):
        await add_characters(maker, TWO, avatar_url=URL)
        bot = Harness(maker, tmp_path)
        await bot.send(callback_update("open:amy"))
        await bot.send(message_update("/new"))
        await bot.send(callback_update("new:bob"))
        assert len(bot.session.named("SendPhoto")) == 3

        async with maker() as s:
            ids = [c.id for c in (await s.execute(select(Conversation))).scalars()]
        bot.session.calls.clear()
        await bot.send(callback_update(f"chat:{ids[0]}"))
        assert len(bot.session.named("SendPhoto")) == 1
        assert bot.session.named("SendMessage") == []

    run_db(scenario)


def test_without_a_picture_the_chat_is_announced_as_text(run_db, tmp_path):
    async def scenario(maker):
        await add_characters(maker, TWO)  # no avatar_url, no local file
        bot = Harness(maker, tmp_path)

        await bot.send(callback_update("open:amy"))

        assert bot.session.named("SendPhoto") == []
        assert t("en", "chat_new", name="Amy") in bot.texts()[-1]

    run_db(scenario)


def test_a_rejected_picture_falls_back_to_text(run_db, tmp_path):
    async def scenario(maker):
        await add_characters(maker, TWO, avatar_url=URL)
        bot = Harness(maker, tmp_path)
        bot.session.photo_error = "Bad Request: wrong file identifier/HTTP URL specified"

        await bot.send(callback_update("open:amy"))

        assert t("en", "chat_new", name="Amy") in bot.texts()[-1]
        assert any(b["callback_data"].startswith("hopen:") for b in bot.buttons())

    run_db(scenario)


def test_groups_are_announced_without_a_picture(run_db, tmp_path):
    async def scenario(maker):
        await add_characters(maker, TWO, avatar_url=URL)
        uid = await make_user(maker)
        async with maker() as s:
            group = await service(s).create_group(uid, ["amy", "bob"])
        bot = Harness(maker, tmp_path)
        await bot.send(message_update("/chats"))
        bot.session.calls.clear()

        await bot.send(callback_update(f"chat:{group.conversation_id}"))

        assert bot.session.named("SendPhoto") == []
        assert t("en", "group_resumed", name="Amy, Bob") in bot.texts()[-1]

    run_db(scenario)


def test_a_caption_over_the_telegram_limit_is_sent_as_text(run_db, tmp_path):
    async def scenario(maker):
        await add_characters(maker, [("&" * 100, "longname", 0, True)], avatar_url=URL)
        bot = Harness(maker, tmp_path)

        await bot.send(callback_update("open:longname"))

        assert bot.session.named("SendPhoto") == []
        assert "&amp;" * 100 in bot.texts()[-1]

    run_db(scenario)


def test_a_stale_remembered_picture_is_forgotten_after_a_failure(run_db, tmp_path):
    async def scenario(maker):
        await add_characters(maker, TWO, avatar_url=URL)
        bot = Harness(maker, tmp_path)

        await bot.send(callback_update("open:amy"))  # sent from the URL, file_id remembered
        await bot.send(callback_update("open:amy"))
        assert bot.session.named("SendPhoto")[-1]["photo"] == "tg-file-id"

        bot.session.photo_error = "Bad Request: wrong file identifier/HTTP URL specified"
        await bot.send(callback_update("open:amy"))  # the stale id is rejected -> text
        bot.session.photo_error = None
        await bot.send(callback_update("open:amy"))

        assert bot.session.named("SendPhoto")[-1]["photo"] == URL

    run_db(scenario)
