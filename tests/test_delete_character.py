"""Deleting a character from the user's side.

Scope: the user's direct chats with it, the memories it holds about the user,
and its place in the user's groups. Nothing else may change.
"""

import pytest
from sqlalchemy import func, select

from app.models import Character, CharacterMemory, Conversation, ConversationParticipant, Message
from app.services.character_memory_service import CharacterMemoryService
from app.services.character_removal_service import CharacterNotFoundError, CharacterRemovalService
from app.services.chat_session_service import ChatSessionService
from app.services.conversation_service import ConversationService
from app.services.telegram_user_service import TelegramUserService
from app.telegram.texts import t
from tests.telegram_harness import Harness, add_characters, callback_update, message_update
from tests.test_conversation_engine import ScriptedProvider

CHARS = [("Amy", "amy", 0, True), ("Bob", "bob", 1, True), ("Cy", "cy", 2, True), ("Dee", "dee", 3, True)]


async def make_user(maker, telegram_id=1001):
    async with maker() as s:
        return (await TelegramUserService(s).get_or_create(telegram_id, "Ada")).id


async def char_id(maker, slug):
    async with maker() as s:
        return (await s.execute(select(Character.id).where(Character.slug == slug))).scalar_one()


async def remember(maker, user_id, slug, key):
    cid = await char_id(maker, slug)
    async with maker() as s:
        await CharacterMemoryService(s).add_memory(
            user_id=user_id, character_id=cid, category="interest",
            content=f"{key} fact", importance=5, confidence=0.9, memory_key=key,
        )
        await s.commit()  # add_memory only flushes; the caller commits


async def count(maker, model):
    async with maker() as s:
        return (await s.execute(select(func.count()).select_from(model))).scalar_one()


async def chat_with(maker, user_id, slug, say=True):
    provider = ScriptedProvider()
    async with maker() as s:
        context = await ChatSessionService(s, provider).open_character_chat(user_id, slug)
    if say:
        async with maker() as s:
            await ConversationService(s, ai_provider=provider).send_message(context.conversation_id, user_id, "hi")
    return context.conversation_id


async def group_of(maker, user_id, slugs):
    async with maker() as s:
        return (await ChatSessionService(s, ScriptedProvider()).create_group(user_id, slugs)).conversation_id


async def remaining_members(maker, conversation_id):
    async with maker() as s:
        rows = (await s.execute(
            select(Character.slug)
            .join(ConversationParticipant, ConversationParticipant.character_id == Character.id)
            .where(ConversationParticipant.conversation_id == conversation_id)
        )).scalars().all()
        return sorted(rows)


# --------------------------------------------------------------- service


def test_removal_deletes_exactly_this_users_data_with_this_character(run_db):
    async def scenario(maker):
        await add_characters(maker, CHARS)
        ada, bea = await make_user(maker, 1), await make_user(maker, 2)

        ada_amy = await chat_with(maker, ada, "amy")
        ada_bob = await chat_with(maker, ada, "bob")
        bea_amy = await chat_with(maker, bea, "amy")
        big_group = await group_of(maker, ada, ["amy", "bob", "cy"])
        small_group = await group_of(maker, ada, ["amy", "dee"])
        other_group = await group_of(maker, ada, ["bob", "cy"])
        for user, slug, key in [(ada, "amy", "a1"), (ada, "amy", "a2"), (ada, "bob", "b1"), (bea, "amy", "x1")]:
            await remember(maker, user, slug, key)

        async with maker() as s:
            summary = await CharacterRemovalService(s).remove(ada, "amy")

        assert (summary.direct_chats, summary.memories, summary.groups, summary.groups_deleted) == (1, 2, 2, 1)

        async with maker() as s:
            ids = set((await s.execute(select(Conversation.id))).scalars())
            memories = (await s.execute(select(CharacterMemory.memory_key))).scalars().all()

        assert ada_amy not in ids and small_group not in ids  # deleted
        assert {ada_bob, bea_amy, big_group, other_group} <= ids  # kept
        assert sorted(memories) == ["b1", "x1"]  # only ada's amy memories went
        assert await remaining_members(maker, big_group) == ["bob", "cy"]  # amy left it
        assert await remaining_members(maker, other_group) == ["bob", "cy"]

        async with maker() as s:  # messages of deleted chats went too; others stay
            owners = set((await s.execute(select(Message.conversation_id))).scalars())
        assert ada_amy not in owners and {ada_bob, bea_amy} <= owners

    run_db(scenario)


def test_preview_matches_removal_and_changes_nothing(run_db):
    async def scenario(maker):
        await add_characters(maker, CHARS)
        ada = await make_user(maker)
        await chat_with(maker, ada, "amy")
        await group_of(maker, ada, ["amy", "bob"])
        await remember(maker, ada, "amy", "k")

        async with maker() as s:
            previewed = await CharacterRemovalService(s).preview(ada, "amy")
        assert (await count(maker, Conversation), await count(maker, CharacterMemory)) == (2, 1)

        async with maker() as s:
            removed = await CharacterRemovalService(s).remove(ada, "amy")

        assert previewed == removed and not previewed.is_empty
        assert (await count(maker, Conversation), await count(maker, CharacterMemory)) == (0, 0)

    run_db(scenario)


def test_nothing_to_delete_is_reported_and_unknown_characters_fail(run_db):
    async def scenario(maker):
        await add_characters(maker, CHARS)
        ada = await make_user(maker)

        async with maker() as s:
            service = CharacterRemovalService(s)
            assert (await service.preview(ada, "amy")).is_empty
            with pytest.raises(CharacterNotFoundError):
                await service.preview(ada, "nobody")
            with pytest.raises(CharacterNotFoundError):
                await service.remove(ada, "nobody")

    run_db(scenario)


def test_inactive_characters_can_still_be_cleaned_up(run_db):
    async def scenario(maker):
        await add_characters(maker, CHARS)
        ada = await make_user(maker)
        await chat_with(maker, ada, "amy")
        await remember(maker, ada, "amy", "k")
        async with maker() as s:
            amy = (await s.execute(select(Character).where(Character.slug == "amy"))).scalar_one()
            amy.is_active = False
            await s.commit()

        async with maker() as s:
            summary = await CharacterRemovalService(s).remove(ada, "amy")

        assert (summary.direct_chats, summary.memories) == (1, 1)
        assert await count(maker, Conversation) == 0 and await count(maker, CharacterMemory) == 0

    run_db(scenario)


def test_a_failed_removal_deletes_nothing(run_db):
    async def scenario(maker):
        await add_characters(maker, CHARS)
        ada = await make_user(maker)
        await chat_with(maker, ada, "amy")
        await group_of(maker, ada, ["amy", "bob"])
        await remember(maker, ada, "amy", "k")
        before = (await count(maker, Conversation), await count(maker, CharacterMemory),
                  await count(maker, ConversationParticipant), await count(maker, Message))

        async with maker() as s:
            async def broken_commit():
                raise RuntimeError("database went away")

            s.commit = broken_commit
            with pytest.raises(RuntimeError):
                await CharacterRemovalService(s).remove(ada, "amy")

        after = (await count(maker, Conversation), await count(maker, CharacterMemory),
                 await count(maker, ConversationParticipant), await count(maker, Message))
        assert after == before

    run_db(scenario)


def test_active_chat_moves_on_after_a_removal(run_db):
    async def scenario(maker):
        await add_characters(maker, CHARS)
        ada = await make_user(maker)
        bob_chat = await chat_with(maker, ada, "bob")
        await chat_with(maker, ada, "amy")  # amy is active

        async with maker() as s:
            await CharacterRemovalService(s).remove(ada, "amy")
        async with maker() as s:
            active = await ChatSessionService(s, ScriptedProvider()).get_active(ada)

        assert active.conversation_id == bob_chat

    run_db(scenario)


# --------------------------------------------------------------- bot flow


def test_delete_button_exists_in_direct_chats_only(run_db, tmp_path):
    async def scenario(maker):
        await add_characters(maker, CHARS)
        bot = Harness(maker, tmp_path)

        await bot.send(callback_update("open:amy"))
        assert "del:amy" in bot.callback_data()

        await bot.send(message_update("/newgroup"))
        await bot.send(callback_update("gsel:0:amy"))
        await bot.send(callback_update("gsel:0:bob"))
        await bot.send(callback_update("gdone"))
        assert not any(d.startswith("del") for d in bot.callback_data())

    run_db(scenario)


def test_confirm_then_delete_flow(run_db, tmp_path):
    async def scenario(maker):
        await add_characters(maker, CHARS)
        bot = Harness(maker, tmp_path, ScriptedProvider(chat_reply="hello"))
        await bot.send(callback_update("open:amy"))
        await bot.send(message_update("hi there"))
        uid = await make_user(maker)
        await remember(maker, uid, "amy", "k")
        await bot.send(message_update("/newgroup"))
        await bot.send(callback_update("gsel:0:amy"))
        await bot.send(callback_update("gsel:0:bob"))
        await bot.send(callback_update("gdone"))
        bot.session.calls.clear()

        await bot.send(callback_update("del:amy"))
        ask = bot.session.named("SendMessage")[0]
        assert ask["text"] == t("en", "delete_confirm", name="Amy", chats=1, memories=1, groups=1, groups_deleted=1)
        assert bot.callback_data() == ["delok:amy", "delno"]
        assert await count(maker, Conversation) == 2  # nothing deleted yet

        await bot.send(callback_update("delok:amy"))
        done = bot.session.named("EditMessageText")[-1]["text"]
        assert done == t("en", "delete_done", name="Amy", chats=1, memories=1, groups=1, groups_deleted=1)
        assert await count(maker, Conversation) == 0 and await count(maker, CharacterMemory) == 0

    run_db(scenario)


def test_cancel_deletes_nothing(run_db, tmp_path):
    async def scenario(maker):
        await add_characters(maker, CHARS)
        bot = Harness(maker, tmp_path)
        await bot.send(callback_update("open:amy"))

        await bot.send(callback_update("del:amy"))
        await bot.send(callback_update("delno"))

        assert bot.session.named("EditMessageText")[-1]["text"] == t("en", "delete_cancelled")
        assert await count(maker, Conversation) == 1

    run_db(scenario)


def test_delete_command_uses_the_active_direct_chat(run_db, tmp_path):
    async def scenario(maker):
        await add_characters(maker, CHARS)
        bot = Harness(maker, tmp_path)

        await bot.send(message_update("/delete"))
        assert bot.texts() == [t("en", "delete_pick")]

        await bot.send(callback_update("open:bob"))
        await bot.send(message_update("/delete"))
        assert t("en", "delete_confirm", name="Bob", chats=1, memories=0, groups=0, groups_deleted=0) == bot.texts()[-1]

        await bot.send(message_update("/newgroup"))
        await bot.send(callback_update("gsel:0:amy"))
        await bot.send(callback_update("gsel:0:bob"))
        await bot.send(callback_update("gdone"))
        await bot.send(message_update("/delete"))  # a group is active: pick a person first
        assert bot.texts()[-1] == t("en", "delete_pick")

    run_db(scenario)


def test_hostile_and_empty_delete_requests(run_db, tmp_path):
    async def scenario(maker):
        await add_characters(maker, CHARS)
        bot = Harness(maker, tmp_path)

        for data in ("del:nobody", "delok:nobody", "del:../../etc", "del:", "del:cy"):
            await bot.send(callback_update(data))

        texts = [a["text"] for a in bot.session.named("AnswerCallbackQuery")]
        assert texts[:4] == [t("en", "character_missing")] * 4
        assert texts[4] == t("en", "delete_nothing", name="Cy")
        assert bot.session.named("SendMessage") == []

    run_db(scenario)


def test_delete_texts_follow_the_users_language(run_db, tmp_path):
    async def scenario(maker):
        await add_characters(maker, CHARS)
        bot = Harness(maker, tmp_path)
        await bot.send(callback_update("open:amy", lang="tr"))

        await bot.send(callback_update("del:amy", lang="tr"))

        assert bot.texts()[-1] == t("tr", "delete_confirm", name="Amy", chats=1, memories=0, groups=0, groups_deleted=0)

    run_db(scenario)
