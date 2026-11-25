"""Persistent groups: creating, listing, switching, and the bot flow.

Membership rules, privacy and navigation of groups (answering is tested in
test_group_messaging.py).
"""

import uuid

import pytest
from sqlalchemy import func, select

from app.models import Character, Conversation, ConversationParticipant, Message
from app.services.chat_session_service import (
    GROUP_MAX_CHARACTERS,
    ChatNotAvailableError,
    ChatSessionService,
    InvalidGroupError,
)
from app.services.telegram_user_service import TelegramUserService
from app.telegram.group_drafts import GroupDrafts
from app.telegram.texts import t
from tests.telegram_harness import Harness, add_characters, callback_update, message_update
from tests.test_conversation_engine import ScriptedProvider

FOUR = [("Amy", "amy", 0, True), ("Bob", "bob", 1, True), ("Cy", "cy", 2, True), ("Dee", "dee", 3, True)]
FIVE = FOUR + [("Eve", "eve", 4, True)]


async def make_user(maker, telegram_id=1001):
    async with maker() as s:
        return (await TelegramUserService(s).get_or_create(telegram_id, "Ada")).id


def service(s):
    return ChatSessionService(s, ScriptedProvider())


# ------------------------------------------------------------ draft store


def test_draft_toggles_limits_and_clears():
    drafts = GroupDrafts()
    assert drafts.get(1) is None

    drafts.start(1)
    assert drafts.toggle(1, "a", 2) and drafts.toggle(1, "b", 2)
    assert not drafts.toggle(1, "c", 2)  # full
    assert drafts.toggle(1, "a", 2)  # untick still works when full
    assert drafts.get(1) == ["b"]

    drafts.get(1).append("x")  # get() hands out a copy
    assert drafts.get(1) == ["b"]
    drafts.clear(1)
    assert drafts.get(1) is None


# --------------------------------------------------------------- service


def test_create_group_makes_a_group_conversation_with_all_members(run_db):
    async def scenario(maker):
        await add_characters(maker, FOUR)
        uid = await make_user(maker)

        async with maker() as s:
            context = await service(s).create_group(uid, ["bob", "amy", "bob"])  # repeat ignored

        assert context.is_group and context.created
        assert [c.slug for c in context.characters] == ["bob", "amy"]
        assert context.name == "Bob, Amy"

        async with maker() as s:
            conversation = (await s.execute(select(Conversation))).scalar_one()
            members = (await s.execute(select(func.count()).select_from(ConversationParticipant))).scalar_one()
        assert (conversation.conversation_type, conversation.user_id, members) == ("group", uid, 2)

    run_db(scenario)


@pytest.mark.parametrize(
    "slugs, reason",
    [
        ([], "too_few"),
        (["amy"], "too_few"),
        (["amy", "amy"], "too_few"),
        (["amy", "bob", "cy", "dee", "eve"], "too_many"),
        (["amy", "missing"], "unavailable"),
        (["amy", "off"], "unavailable"),
    ],
)
def test_invalid_groups_are_refused_and_nothing_is_saved(run_db, slugs, reason):
    async def scenario(maker):
        await add_characters(maker, FIVE + [("Off", "off", 5, False)])
        uid = await make_user(maker)

        async with maker() as s:
            with pytest.raises(InvalidGroupError) as error:
                await service(s).create_group(uid, slugs)
        assert error.value.reason == reason

        async with maker() as s:
            assert (await s.execute(select(func.count()).select_from(Conversation))).scalar_one() == 0

    assert GROUP_MAX_CHARACTERS == 4
    run_db(scenario)


def test_group_becomes_the_active_chat_and_lists_with_its_members(run_db):
    async def scenario(maker):
        await add_characters(maker, FOUR)
        uid = await make_user(maker)

        async with maker() as s:
            svc = service(s)
            direct = await svc.open_character_chat(uid, "amy")
            group = await svc.create_group(uid, ["amy", "bob"])
            active = await svc.get_active(uid)
            listing = (await svc.list_chats(uid)).items

        assert active.conversation_id == group.conversation_id and active.is_group
        assert [(c.is_group, c.is_active) for c in listing] == [(True, True), (False, False)]
        assert listing[0].name == "Amy, Bob"
        assert listing[1].conversation_id == direct.conversation_id

    run_db(scenario)


def test_opening_a_character_never_lands_in_a_group_with_it(run_db):
    async def scenario(maker):
        await add_characters(maker, FOUR)
        uid = await make_user(maker)

        async with maker() as s:
            svc = service(s)
            group = await svc.create_group(uid, ["amy", "bob"])
            opened = await svc.open_character_chat(uid, "amy")

        assert opened.created and not opened.is_group
        assert opened.conversation_id != group.conversation_id

    run_db(scenario)


def test_switching_to_a_group_and_its_history(run_db):
    async def scenario(maker):
        await add_characters(maker, FOUR)
        uid = await make_user(maker)

        async with maker() as s:
            svc = service(s)
            group = await svc.create_group(uid, ["amy", "bob"])
            await svc.open_character_chat(uid, "cy")  # cy is active now
            switched = await svc.switch_to(uid, group.conversation_id)
            history = await svc.get_history(uid, group.conversation_id)

        assert switched.is_group and (await _active(maker, uid)).conversation_id == group.conversation_id
        assert history.is_group and history.messages == [] and history.name == "Amy, Bob"

    async def _active(maker, uid):
        async with maker() as s:
            return await service(s).get_active(uid)

    run_db(scenario)


def test_groups_are_private_and_hidden_when_any_member_is_inactive(run_db):
    async def scenario(maker):
        await add_characters(maker, FOUR)
        ada, bea = await make_user(maker, 1), await make_user(maker, 2)

        async with maker() as s:
            svc = service(s)
            group = await svc.create_group(ada, ["amy", "bob"])
            with pytest.raises(ChatNotAvailableError):
                await svc.switch_to(bea, group.conversation_id)
            with pytest.raises(ChatNotAvailableError):
                await svc.get_history(bea, group.conversation_id)
            assert (await svc.list_chats(bea)).items == []

            bob = (await s.execute(select(Character).where(Character.slug == "bob"))).scalar_one()
            bob.is_active = False
            await s.commit()

            assert await svc.get_active(ada) is None
            assert (await svc.list_chats(ada)).items == []
            with pytest.raises(ChatNotAvailableError):
                await svc.switch_to(ada, group.conversation_id)

    run_db(scenario)


# -------------------------------------------------------------- bot flow


async def start_picker(bot):
    await bot.send(message_update("/newgroup"))
    return bot.session.named("SendMessage")[-1]


def picker_buttons(call):
    return [b for row in call["reply_markup"]["inline_keyboard"] for b in row]


def test_full_group_creation_flow(run_db, tmp_path):
    async def scenario(maker):
        await add_characters(maker, FOUR)
        bot = Harness(maker, tmp_path)

        picker = await start_picker(bot)
        assert "(0 selected)" in picker["text"]
        assert [b["callback_data"] for b in picker_buttons(picker)][:2] == ["gsel:0:amy", "gsel:0:bob"]

        await bot.send(callback_update("gsel:0:amy"))
        await bot.send(callback_update("gsel:0:cy"))
        edited = bot.session.named("EditMessageText")[-1]
        assert "(2 selected)" in edited["text"]
        labels = [b["text"] for b in picker_buttons(edited)]
        assert "✓ Amy" in labels and "✓ Cy" in labels and "Bob" in labels
        assert t("en", "btn_create_group", n=2) in labels

        bot.session.calls.clear()
        await bot.send(callback_update("gdone"))

        confirm = bot.session.named("EditMessageText")[0]
        assert "Amy, Cy" in confirm["text"] and "reply_markup" not in confirm
        announce = bot.session.named("SendMessage")[0]["text"]
        assert announce == (
            t("en", "chat_divider", name="Amy, Cy", icon="👥") + "\n" + t("en", "group_ready", name="Amy, Cy")
        )
        assert [d[:6] for d in bot.callback_data()] == ["hopen:"]  # history only, no "new chat"

        async with maker() as s:
            assert (await service(s).get_active(await make_user(maker))).is_group

    run_db(scenario)


def test_group_picker_limits_expiry_and_cancel(run_db, tmp_path):
    async def scenario(maker):
        await add_characters(maker, FIVE)
        bot = Harness(maker, tmp_path)

        await bot.send(callback_update("gsel:0:amy"))  # no picker started: expired
        await bot.send(callback_update("gdone"))
        await bot.send(callback_update("gpage:0"))
        alerts = bot.session.named("AnswerCallbackQuery")
        assert [a["text"] for a in alerts] == [t("en", "group_expired")] * 3

        bot.session.calls.clear()
        await start_picker(bot)
        for slug in ("amy", "bob", "cy", "dee", "eve"):
            await bot.send(callback_update(f"gsel:0:{slug}"))
        answers = bot.session.named("AnswerCallbackQuery")
        assert answers[-1]["text"] == t("en", "group_max", max=4) and answers[-1]["show_alert"]

        await bot.send(callback_update("gsel:0:amy"))  # untick one
        await bot.send(callback_update("gcancel"))
        assert bot.session.named("EditMessageText")[-1]["text"] == t("en", "group_cancelled")
        await bot.send(callback_update("gdone"))  # draft is gone
        assert bot.session.named("AnswerCallbackQuery")[-1]["text"] == t("en", "group_expired")

        async with maker() as s:
            assert (await s.execute(select(func.count()).select_from(Conversation))).scalar_one() == 0

    run_db(scenario)


def test_group_needs_two_characters_and_rejects_hostile_input(run_db, tmp_path):
    async def scenario(maker):
        await add_characters(maker, FOUR + [("Off", "off", 9, False)])
        bot = Harness(maker, tmp_path)
        await start_picker(bot)
        await bot.send(callback_update("gsel:0:amy"))

        await bot.send(callback_update("gdone"))
        assert bot.session.named("AnswerCallbackQuery")[-1]["text"] == t("en", "group_min", min=2)

        for data in ("gsel:0:off", "gsel:0:missing", "gsel:0:../../etc", "gsel:", "gsel:zz:amy"):
            await bot.send(callback_update(data))
        answers = bot.session.named("AnswerCallbackQuery")
        assert [a["text"] for a in answers[-5:-1]] == [t("en", "group_unavailable")] * 4

        async with maker() as s:
            assert (await s.execute(select(func.count()).select_from(Conversation))).scalar_one() == 0

    run_db(scenario)


def test_picker_pages_and_keeps_ticks_across_pages(run_db, tmp_path):
    async def scenario(maker):
        await add_characters(maker, [(f"C{i}", f"c{i}", i, True) for i in range(8)])
        bot = Harness(maker, tmp_path)
        await start_picker(bot)
        await bot.send(callback_update("gsel:0:c0"))

        await bot.send(callback_update("gpage:1"))
        page2 = bot.session.named("EditMessageText")[-1]
        data = [b["callback_data"] for b in picker_buttons(page2)]
        assert data[:2] == ["gsel:1:c6", "gsel:1:c7"] and "gpage:0" in data

        await bot.send(callback_update("gpage:0"))
        labels = [b["text"] for b in picker_buttons(bot.session.named("EditMessageText")[-1])]
        assert "✓ C0" in labels

    run_db(scenario)


def test_chats_list_offers_new_group_and_shows_groups(run_db, tmp_path):
    async def scenario(maker):
        await add_characters(maker, FOUR)
        bot = Harness(maker, tmp_path)

        await bot.send(message_update("/chats"))  # nothing yet, but groups can start here
        assert bot.texts() == [t("en", "chats_empty")] and bot.callback_data() == ["gnew"]

        await start_picker(bot)
        await bot.send(callback_update("gsel:0:amy"))
        await bot.send(callback_update("gsel:0:bob"))
        await bot.send(callback_update("gdone"))
        await bot.send(callback_update("gnew"))  # the button also starts the picker
        assert "(0 selected)" in bot.session.named("SendMessage")[-1]["text"]

        await bot.send(message_update("/chats"))
        first = picker_buttons(bot.session.named("SendMessage")[-1])[0]
        assert first["text"].startswith("● 👥 Amy, Bob")

    run_db(scenario)


def test_new_chat_is_not_offered_inside_a_group(run_db, tmp_path):
    async def scenario(maker):
        await add_characters(maker, FOUR)
        bot = Harness(maker, tmp_path)
        await start_picker(bot)
        await bot.send(callback_update("gsel:0:amy"))
        await bot.send(callback_update("gsel:0:bob"))
        await bot.send(callback_update("gdone"))

        await bot.send(message_update("/new"))  # no "new chat" in a group
        assert bot.texts()[-1] == t("en", "new_chat_in_group")

    run_db(scenario)


def test_switching_to_a_group_from_the_list_and_turkish_texts(run_db, tmp_path):
    async def scenario(maker):
        await add_characters(maker, FOUR)
        bot = Harness(maker, tmp_path)
        await bot.send(callback_update("open:cy", lang="tr"))
        await start_picker(bot)
        await bot.send(callback_update("gsel:0:amy", lang="tr"))
        await bot.send(callback_update("gsel:0:bob", lang="tr"))
        await bot.send(callback_update("gdone", lang="tr"))
        await bot.send(callback_update("open:cy", lang="tr"))  # cy active again

        await bot.send(message_update("/chats", lang="tr"))
        group_button = next(b for b in picker_buttons(bot.session.named("SendMessage")[-1]) if "👥" in b["text"])
        await bot.send(callback_update(group_button["callback_data"], lang="tr"))

        text = bot.texts()[-1]
        assert text == (
            t("tr", "chat_divider", name="Amy, Bob", icon="👥") + "\n" + t("tr", "group_resumed", name="Amy, Bob")
        )

    run_db(scenario)


def test_group_ids_in_callbacks_are_validated(run_db, tmp_path):
    async def scenario(maker):
        await add_characters(maker, FOUR)
        bot = Harness(maker, tmp_path)
        for data in (f"chat:{uuid.uuid4()}", "chat:zzz"):
            await bot.send(callback_update(data))
        alerts = bot.session.named("AnswerCallbackQuery")
        assert len(alerts) == 2 and all(a["show_alert"] for a in alerts)

    run_db(scenario)
