"""Personal chat: active chat, switching, messaging through the bot.

Database tests need a disposable database (see tests/conftest.py).
"""

import asyncio
import uuid

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models import Conversation, Message, User
from app.services.chat_session_service import ChatNotAvailableError, ChatSessionService
from app.services.conversation_service import ConversationService
from app.services.telegram_user_service import TelegramUserService
from app.telegram.texts import t
from tests.telegram_harness import (
    Harness,
    add_characters,
    callback_update,
    message_update,
    photo_message_update,
)
from tests.test_conversation_engine import ScriptedProvider


async def make_user(maker, telegram_id=1001):
    async with maker() as s:
        return (await TelegramUserService(s).get_or_create(telegram_id, "Ada")).id


async def conversations_of(maker, user_id):
    async with maker() as s:
        rows = (await s.execute(select(Conversation).where(Conversation.user_id == user_id))).scalars().all()
        return rows


# ------------------------------------------------------ service behaviour


def test_open_continues_the_same_chat_and_new_starts_another(run_db):
    async def scenario(maker):
        await add_characters(maker, [("Amy", "amy", 0, True)])
        uid = await make_user(maker)

        async with maker() as s:
            service = ChatSessionService(s, ScriptedProvider())
            first = await service.open_character_chat(uid, "amy")
            again = await service.open_character_chat(uid, "amy")
            fresh = await service.start_new_chat(uid, "amy")
            active = await service.get_active(uid)

        assert first.created and not again.created
        assert first.conversation_id == again.conversation_id
        assert fresh.created and fresh.conversation_id != first.conversation_id
        assert active.conversation_id == fresh.conversation_id
        assert len(await conversations_of(maker, uid)) == 2

    run_db(scenario)


def test_opening_a_character_continues_its_latest_chat_not_the_active_one(run_db):
    async def scenario(maker):
        await add_characters(maker, [("Amy", "amy", 0, True), ("Bob", "bob", 1, True)])
        uid = await make_user(maker)

        async with maker() as s:
            service = ChatSessionService(s, ScriptedProvider())
            amy = await service.open_character_chat(uid, "amy")
            await service.open_character_chat(uid, "bob")
            back = await service.open_character_chat(uid, "amy")
            active = await service.get_active(uid)

        assert back.conversation_id == amy.conversation_id
        assert active.character.slug == "amy"

    run_db(scenario)


def test_switch_and_list_chats_order_and_active_flag(run_db):
    async def scenario(maker):
        await add_characters(maker, [("Amy", "amy", 0, True), ("Bob", "bob", 1, True)])
        uid = await make_user(maker)

        async with maker() as s:
            service = ChatSessionService(s, ScriptedProvider())
            amy = await service.open_character_chat(uid, "amy")
            bob = await service.open_character_chat(uid, "bob")
            assert [(c.character.slug, c.is_active) for c in (await service.list_chats(uid)).items] == [
                ("bob", True), ("amy", False)]

            await service.switch_to(uid, amy.conversation_id)
            chats = (await service.list_chats(uid)).items

        assert [(c.character.slug, c.is_active) for c in chats] == [("amy", True), ("bob", False)]
        assert chats[1].conversation_id == bob.conversation_id

    run_db(scenario)


def test_users_cannot_see_or_switch_to_each_others_chats(run_db):
    async def scenario(maker):
        await add_characters(maker, [("Amy", "amy", 0, True)])
        ada, bea = await make_user(maker, 1), await make_user(maker, 2)

        async with maker() as s:
            service = ChatSessionService(s, ScriptedProvider())
            adas = await service.open_character_chat(ada, "amy")
            await service.open_character_chat(bea, "amy")

            assert len((await service.list_chats(bea)).items) == 1
            assert (await service.get_active(bea)).conversation_id != adas.conversation_id
            with pytest.raises(ChatNotAvailableError):
                await service.switch_to(bea, adas.conversation_id)
            assert await service.last_character_message(bea, adas.conversation_id) is None

    run_db(scenario)


def test_inactive_characters_cannot_be_chatted_with_and_disappear_from_lists(run_db):
    async def scenario(maker):
        await add_characters(maker, [("Amy", "amy", 0, True), ("Off", "off", 1, False)])
        uid = await make_user(maker)

        async with maker() as s:
            service = ChatSessionService(s, ScriptedProvider())
            await service.open_character_chat(uid, "amy")
            for slug in ("off", "missing"):
                with pytest.raises(ChatNotAvailableError):
                    await service.open_character_chat(uid, slug)
                with pytest.raises(ChatNotAvailableError):
                    await service.start_new_chat(uid, slug)

            from app.models import Character
            amy = (await s.execute(select(Character).where(Character.slug == "amy"))).scalar_one()
            amy.is_active = False
            await s.commit()

            assert await service.get_active(uid) is None
            assert (await service.list_chats(uid)).items == []

    run_db(scenario)


def test_background_summary_does_not_change_the_active_chat(run_db):
    async def scenario(maker):
        await add_characters(maker, [("Amy", "amy", 0, True), ("Bob", "bob", 1, True)])
        uid = await make_user(maker)
        provider = ScriptedProvider()

        async with maker() as s:
            service = ChatSessionService(s, provider)
            amy = await service.open_character_chat(uid, "amy")
            bob = await service.open_character_chat(uid, "bob")  # bob is active

        async with maker() as s:
            engine = ConversationService(s, ai_provider=provider)
            for i in range(6):  # 12 messages: a summary is written for amy's chat
                await engine.send_message(amy.conversation_id, uid, f"message {i}")
        assert provider.summaries >= 1

        async with maker() as s:
            active = await ChatSessionService(s, provider).get_active(uid)
        assert active.conversation_id == bob.conversation_id

    run_db(scenario)


# ------------------------------------------------------------ bot flows


async def seeded(maker, tmp_path, provider=None, characters=(("Amy", "amy", 0, True),)):
    await add_characters(maker, list(characters))
    return Harness(maker, tmp_path, provider)


def test_text_without_a_chat_asks_to_pick_a_character(run_db, tmp_path):
    async def scenario(maker):
        provider = ScriptedProvider()
        bot = await seeded(maker, tmp_path, provider)

        await bot.send(message_update("hello"))

        assert bot.texts() == [t("en", "no_active_chat")]
        assert provider.last_chat_prompt == ""

    run_db(scenario)


def test_open_button_then_text_gets_a_reply_and_is_saved(run_db, tmp_path):
    async def scenario(maker):
        provider = ScriptedProvider(chat_reply="Hi Ada, I'm Amy!")
        bot = await seeded(maker, tmp_path, provider)

        await bot.send(callback_update("open:amy"))
        await bot.send(message_update("Hello Amy"))

        started, reply = bot.texts()
        assert "Amy" in started and t("en", "chat_new", name="Amy") == started
        data = bot.callback_data(index=0)
        assert data[0].startswith("hopen:") and data[1] == "new:amy"
        assert reply == "Hi Ada, I'm Amy!"
        assert "You are a test character." in provider.last_chat_prompt

        async with maker() as s:
            msgs = (await s.execute(select(Message).order_by(Message.created_at))).scalars().all()
        assert [(m.sender_type, m.content) for m in msgs] == [
            ("user", "Hello Amy"), ("character", "Hi Ada, I'm Amy!")]

    run_db(scenario)


def test_replies_are_plain_text_never_html(run_db, tmp_path):
    async def scenario(maker):
        provider = ScriptedProvider(chat_reply="<b>bold</b> & <i>x")
        bot = await seeded(maker, tmp_path, provider)
        await bot.send(callback_update("open:amy"))

        await bot.send(message_update("hi"))

        last = bot.session.named("SendMessage")[-1]
        assert last["text"] == "<b>bold</b> & <i>x"
        assert last.get("parse_mode") is None

    run_db(scenario)


def test_long_replies_are_split_into_telegram_sized_messages(run_db, tmp_path):
    async def scenario(maker):
        provider = ScriptedProvider(chat_reply=("word " * 1500).strip())
        bot = await seeded(maker, tmp_path, provider)
        await bot.send(callback_update("open:amy"))

        await bot.send(message_update("write a lot"))

        parts = bot.texts()[1:]
        assert len(parts) >= 2 and all(len(p) <= 4096 for p in parts)

    run_db(scenario)


def test_provider_failure_tells_the_user_and_keeps_their_message(run_db, tmp_path):
    async def scenario(maker):
        provider = ScriptedProvider(fail={"chat"})
        bot = await seeded(maker, tmp_path, provider)
        await bot.send(callback_update("open:amy"))

        await bot.send(message_update("are you there?"))

        assert bot.texts()[-1] == t("en", "ai_error")
        async with maker() as s:
            saved = (await s.execute(select(Message.content))).scalars().all()
        assert saved == ["are you there?"]

    run_db(scenario)


def test_unexpected_errors_are_reported_to_the_user(run_db, tmp_path, monkeypatch):
    async def scenario(maker):
        monkeypatch.setattr(settings, "GROQ_API_KEY", "")
        bot = await seeded(maker, tmp_path)
        await bot.send(callback_update("open:amy"))
        bot.dispatcher.workflow_data["provider"] = None  # engine would build a real provider

        await bot.send(message_update("hi"))

        assert bot.texts()[-1] == t("en", "error")

    run_db(scenario)


def test_resuming_shows_where_we_left_off_escaped(run_db, tmp_path):
    async def scenario(maker):
        provider = ScriptedProvider(chat_reply="See you <soon> & later")
        bot = await seeded(maker, tmp_path, provider)
        await bot.send(callback_update("open:amy"))
        await bot.send(message_update("bye"))

        await bot.send(callback_update("open:amy"))

        text = bot.texts()[-1]
        assert text.startswith(t("en", "chat_resumed", name="Amy"))
        assert "See you &lt;soon&gt; &amp; later" in text

    run_db(scenario)


def test_quick_messages_are_answered_one_at_a_time_in_order(run_db, tmp_path):
    class SlowProvider(ScriptedProvider):
        def __init__(self):
            super().__init__()
            self.running = 0
            self.max_running = 0
            self.seen = []

        async def generate_response(self, system_prompt, messages):
            if "memory" in system_prompt.lower():
                return await super().generate_response(system_prompt, messages)
            self.running += 1
            self.max_running = max(self.max_running, self.running)
            self.seen.append(messages[-1]["content"])
            await asyncio.sleep(0.05)
            self.running -= 1
            return f"re: {messages[-1]['content']}"

    async def scenario(maker):
        provider = SlowProvider()
        bot = await seeded(maker, tmp_path, provider)
        await bot.send(callback_update("open:amy"))

        await asyncio.gather(*(bot.send(message_update(f"m{i}")) for i in range(4)))

        assert provider.max_running == 1
        assert provider.seen == ["m0", "m1", "m2", "m3"]
        assert bot.texts()[1:] == ["re: m0", "re: m1", "re: m2", "re: m3"]

    run_db(scenario)


def test_menu_buttons_and_commands_never_reach_the_character(run_db, tmp_path):
    async def scenario(maker):
        provider = ScriptedProvider()
        bot = await seeded(maker, tmp_path, provider)
        await bot.send(callback_update("open:amy"))
        before = len(bot.texts())

        await bot.send(message_update(t("en", "menu_characters")))
        await bot.send(message_update(t("tr", "menu_chats")))
        await bot.send(message_update("/nonsense"))
        await bot.send(photo_message_update())

        assert provider.last_chat_prompt == ""
        assert len(bot.texts()) - before == 4  # gallery, chats, unknown, text-only
        assert bot.texts()[-1] == t("en", "text_only")
        assert t("en", "unknown_command") in bot.texts()

    run_db(scenario)


def test_chats_menu_lists_chats_and_switching_routes_messages(run_db, tmp_path):
    async def scenario(maker):
        provider = ScriptedProvider(chat_reply="ok")
        bot = await seeded(maker, tmp_path, provider,
                           characters=(("Amy", "amy", 0, True), ("Bob", "bob", 1, True)))
        await bot.send(callback_update("open:amy"))
        await bot.send(callback_update("open:bob"))  # bob active

        await bot.send(message_update("/chats"))
        buttons = bot.buttons()
        assert buttons[0]["text"].startswith("● Bob")
        amy_button = next(b for b in buttons if "Amy" in b["text"])

        await bot.send(callback_update(amy_button["callback_data"]))
        await bot.send(message_update("hello from the switch"))

        async with maker() as s:
            rows = (await s.execute(
                select(Message.content, Conversation.title)
                .join(Conversation, Conversation.id == Message.conversation_id)
                .where(Message.sender_type == "user")
            )).all()
        assert rows == [("hello from the switch", "Amy")]

    run_db(scenario)


def test_empty_chat_list_and_hostile_chat_callbacks(run_db, tmp_path):
    async def scenario(maker):
        await add_characters(maker, [("Amy", "amy", 0, True)])
        bot = Harness(maker, tmp_path)
        other = await make_user(maker, 2)
        async with maker() as s:
            foreign = (await ChatSessionService(s, ScriptedProvider()).open_character_chat(other, "amy")).conversation_id

        await bot.send(message_update("/chats"))
        assert bot.texts() == [t("en", "chats_empty")]

        for data in ("chat:not-a-uuid", f"chat:{uuid.uuid4()}", f"chat:{foreign}", "chat:"):
            await bot.send(callback_update(data))

        alerts = bot.session.named("AnswerCallbackQuery")
        assert len(alerts) == 4 and all(a["show_alert"] for a in alerts)
        async with maker() as s:  # the foreign chat was not touched/stolen
            assert await ChatSessionService(s, None).get_active(other) is not None

    run_db(scenario)


def test_unknown_or_inactive_character_gives_an_alert(run_db, tmp_path):
    async def scenario(maker):
        bot = await seeded(maker, tmp_path, characters=(("Off", "off", 0, False),))

        for data in ("open:off", "open:missing", "open:../../etc", "new:off", "open:"):
            await bot.send(callback_update(data))

        alerts = bot.session.named("AnswerCallbackQuery")
        assert len(alerts) == 5 and all(a["show_alert"] for a in alerts)
        assert bot.session.named("SendMessage") == []

    run_db(scenario)


def test_new_chat_button_and_command_start_fresh_conversations(run_db, tmp_path):
    async def scenario(maker):
        bot = await seeded(maker, tmp_path)
        uid = await make_user(maker)

        await bot.send(message_update("/new"))
        assert bot.texts() == [t("en", "no_active_chat")]

        await bot.send(callback_update("open:amy"))
        await bot.send(callback_update("new:amy"))
        await bot.send(message_update("/new"))

        assert len(await conversations_of(maker, uid)) == 3

    run_db(scenario)


def test_tr_user_gets_turkish_chat_texts(run_db, tmp_path):
    async def scenario(maker):
        bot = await seeded(maker, tmp_path)

        await bot.send(callback_update("open:amy", lang="tr"))

        assert bot.texts() == [t("tr", "chat_new", name="Amy")]

    run_db(scenario)


# ----------------------------------------------- paging and history (service)


async def open_many(maker, uid, count, slug="amy"):
    async with maker() as s:
        service = ChatSessionService(s, ScriptedProvider())
        ids = [(await service.open_character_chat(uid, slug)).conversation_id]
        for _ in range(count - 1):
            ids.append((await service.start_new_chat(uid, slug)).conversation_id)
    return ids  # oldest first; the last one is active


def test_chat_list_is_paged_with_the_active_chat_first(run_db):
    async def scenario(maker):
        await add_characters(maker, [("Amy", "amy", 0, True)])
        uid = await make_user(maker)
        ids = await open_many(maker, uid, 7)

        async with maker() as s:
            service = ChatSessionService(s, ScriptedProvider())
            first = await service.list_chats(uid, 0, page_size=3)
            second = await service.list_chats(uid, 1, page_size=3)
            last = await service.list_chats(uid, 99, page_size=3)
            negative = await service.list_chats(uid, -4, page_size=3)

        assert (first.total_pages, first.page) == (3, 0)
        assert [c.conversation_id for c in first.items] == ids[::-1][:3]
        assert [c.is_active for c in first.items] == [True, False, False]
        assert not any(c.is_active for c in second.items)
        assert [c.conversation_id for c in second.items] == ids[::-1][3:6]
        assert last.page == 2 and [c.conversation_id for c in last.items] == [ids[0]]
        assert negative.page == 0

    run_db(scenario)


def test_history_pages_start_with_the_newest_and_read_oldest_first(run_db):
    async def scenario(maker):
        await add_characters(maker, [("Amy", "amy", 0, True)])
        uid = await make_user(maker)
        provider = ScriptedProvider(chat_reply="reply")
        (cid,) = await open_many(maker, uid, 1)
        async with maker() as s:
            engine = ConversationService(s, ai_provider=provider)
            for i in range(3):
                await engine.send_message(cid, uid, f"u{i}")  # 6 messages

        async with maker() as s:
            service = ChatSessionService(s, provider)
            newest = await service.get_history(uid, cid, 0, page_size=4)
            older = await service.get_history(uid, cid, 1, page_size=4)
            clamped = await service.get_history(uid, cid, 50, page_size=4)

        assert newest.total_pages == 2
        assert [(m.from_user, m.content) for m in newest.messages] == [
            (True, "u1"), (False, "reply"), (True, "u2"), (False, "reply")]
        assert [(m.from_user, m.content) for m in older.messages] == [(True, "u0"), (False, "reply")]
        assert clamped.page == 1

    run_db(scenario)


def test_history_is_private_and_empty_chats_have_one_empty_page(run_db):
    async def scenario(maker):
        await add_characters(maker, [("Amy", "amy", 0, True)])
        ada, bea = await make_user(maker, 1), await make_user(maker, 2)
        (cid,) = await open_many(maker, ada, 1)

        async with maker() as s:
            service = ChatSessionService(s, ScriptedProvider())
            empty = await service.get_history(ada, cid)
            assert (empty.messages, empty.total_pages, empty.page) == ([], 1, 0)
            with pytest.raises(ChatNotAvailableError):
                await service.get_history(bea, cid)
            with pytest.raises(ChatNotAvailableError):
                await service.get_history(ada, uuid.uuid4())

    run_db(scenario)


# ------------------------------------------------------- paging and history (bot)


def test_chats_list_has_page_buttons_that_edit_in_place(run_db, tmp_path):
    async def scenario(maker):
        bot = await seeded(maker, tmp_path)
        uid = await make_user(maker)
        await open_many(maker, uid, 7)

        await bot.send(message_update("/chats"))
        first = bot.callback_data()
        assert first[-3:] == ["noop", "chats:1", "gnew"] and len(first) == 5 + 3

        await bot.send(callback_update("chats:1"))
        edited = bot.session.named("EditMessageText")[0]
        assert "(2/2)" in edited["text"]
        assert "●" not in str(edited["reply_markup"])  # active chat is on page 1
        assert bot.callback_data("EditMessageText")[-3:] == ["chats:0", "noop", "gnew"]
        for data in ("chats:abc", "chats:99999999999999999", "chats:"):
            await bot.send(callback_update(data))

    run_db(scenario)


def test_history_button_menu_and_paging_in_the_bot(run_db, tmp_path):
    async def scenario(maker):
        provider = ScriptedProvider(chat_reply="Re <b>")
        bot = await seeded(maker, tmp_path, provider)
        await bot.send(callback_update("open:amy"))
        hopen = bot.callback_data(index=0)[0]
        for i in range(5):  # 10 messages -> 2 pages of 8
            await bot.send(message_update(f"msg {i} <x>"))
        bot.session.calls.clear()

        await bot.send(callback_update(hopen))
        shown = bot.session.named("SendMessage")[-1]
        assert "(1/2)" in shown["text"]
        assert "<b>You:</b> msg 4 &lt;x&gt;" in shown["text"]
        assert "<b>Amy:</b> Re &lt;b&gt;" in shown["text"]
        assert "<x>" not in shown["text"]
        nav = [b["callback_data"] for row in shown["reply_markup"]["inline_keyboard"] for b in row]
        assert nav[0].endswith(":1") and nav[1] == "noop" and len(nav) == 2  # only "older"

        await bot.send(callback_update(nav[0]))  # older page, edited in place
        edited = bot.session.named("EditMessageText")[-1]
        assert "(2/2)" in edited["text"] and "msg 0" in edited["text"]

        await bot.send(message_update(t("tr", "menu_history")))  # bottom-menu button
        await bot.send(message_update("/history"))
        assert "(1/2)" in bot.session.named("SendMessage")[-1]["text"]

    run_db(scenario)


def test_history_commands_without_a_chat_and_hostile_history_callbacks(run_db, tmp_path):
    async def scenario(maker):
        provider = ScriptedProvider()
        bot = await seeded(maker, tmp_path, provider)
        other = await make_user(maker, 2)
        (foreign,) = await open_many(maker, other, 1)

        await bot.send(message_update("/history"))
        await bot.send(message_update(t("en", "menu_history")))
        assert bot.texts() == [t("en", "no_active_chat")] * 2
        assert provider.last_chat_prompt == ""  # menu text never reached the character

        for data in ("hopen:nope", f"hopen:{foreign}", f"hist:{foreign}:0", "hist:", "hist:x:y"):
            await bot.send(callback_update(data))
        alerts = bot.session.named("AnswerCallbackQuery")
        assert len(alerts) == 5 and all(a["show_alert"] for a in alerts)
        assert bot.session.named("EditMessageText") == []

    run_db(scenario)
