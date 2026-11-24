"""Group messaging (single speaker): who answers, memory fan-out, isolation."""

import json

import pytest
from sqlalchemy import select

from app.models import CharacterMemory, Conversation, Message
from app.services.chat_session_service import ChatSessionService
from app.services.conversation_service import AIResponseError
from app.services.group_conversation_service import GroupConversationService
from app.services.group_context_builder import label_messages
from app.services.speaker_selection import GroupMember, select_speaker
from app.services.telegram_user_service import TelegramUserService
from tests.telegram_harness import Harness, add_characters, callback_update, message_update
from tests.test_conversation_engine import ONE_MEMORY, ScriptedProvider

TRIO = [("Amy", "amy", 0, True), ("Bob", "bob", 1, True), ("Cy", "cy", 2, True)]


def member(name, slug=None):
    return GroupMember(id=name, slug=slug or name.lower(), name=name)


class PromptLog(ScriptedProvider):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.chat_prompts = []
        self.chat_messages = []

    async def generate_response(self, system_prompt, messages):
        reply = await super().generate_response(system_prompt, messages)
        low = system_prompt.lower()
        if "long-term memory extraction system" not in low and "long-term conversation memory manager" not in low:
            self.chat_prompts.append(system_prompt)
            self.chat_messages.append(messages)
        return reply


async def make_group(maker, slugs=("amy", "bob"), telegram_id=1001):
    async with maker() as s:
        user = await TelegramUserService(s).get_or_create(telegram_id, "Ada")
        user_id = user.id
        ctx = await ChatSessionService(s).create_group(user_id, list(slugs))
        return user_id, ctx.conversation_id


# ------------------------------------------------------ speaker selection


def test_addressed_character_speaks():
    amy, bob = member("Amy"), member("Bob")
    assert select_speaker("Bob, how are you?", [amy, bob]).member is bob
    assert select_speaker("Bob, how are you?", [amy, bob]).reason == "addressed"
    assert select_speaker("@amy hi", [amy, bob]).member is amy
    assert select_speaker("what do you think, Bob?", [amy, bob]).member is bob


def test_continuation_and_default():
    amy, bob = member("Amy"), member("Bob")
    choice = select_speaker("tell me more", [amy, bob], last_speaker_id="Bob")
    assert (choice.member, choice.reason) == (bob, "continuation")
    choice = select_speaker("hello all", [amy, bob])
    assert (choice.member, choice.reason) == (amy, "default")


def test_addressing_beats_continuation_and_unknown_last_speaker_is_ignored():
    amy, bob = member("Amy"), member("Bob")
    assert select_speaker("Amy, you?", [amy, bob], last_speaker_id="Bob").member is amy
    assert select_speaker("hi", [amy, bob], last_speaker_id="ghost").reason == "default"


def test_no_members_is_an_error():
    with pytest.raises(ValueError):
        select_speaker("hi", [])


def test_label_messages_roles_and_names():
    class M:
        def __init__(self, sender_type, content, cid=None):
            self.sender_type, self.content, self.sender_character_id = sender_type, content, cid

    out = label_messages(
        [M("user", "hi"), M("character", "yo", "a"), M("character", "hey", "b")],
        "a",
        {"a": "Amy", "b": "Bob"},
        "Ada",
    )
    assert out == [
        {"role": "user", "content": "Ada: hi"},
        {"role": "assistant", "content": "yo"},
        {"role": "user", "content": "Bob: hey"},
    ]


# ----------------------------------------------------------- the service


def test_group_reply_is_saved_for_the_speaker_and_prompt_lists_the_room(run_db):
    async def scenario(maker):
        await add_characters(maker, TRIO)
        user_id, conv_id = await make_group(maker)
        provider = PromptLog(chat_reply="Bob: Hello there")

        async with maker() as s:
            reply = await GroupConversationService(s, provider).send_message(conv_id, user_id, "Bob, hi!")

        assert reply.speaker.name == "Bob" and reply.reason == "addressed"
        assert reply.content == "Hello there"  # the model's own-name prefix is dropped
        async with maker() as s:
            rows = (await s.execute(select(Message).order_by(Message.created_at))).scalars().all()
        assert [r.sender_type for r in rows] == ["user", "character"]
        assert rows[1].sender_character_id == reply.speaker.id
        assert rows[1].content == "Hello there"
        assert "Amy" in provider.chat_prompts[-1] and "Bob" in provider.chat_prompts[-1]
        assert provider.chat_messages[-1][-1] == {"role": "user", "content": "Ada: Bob, hi!"}

    run_db(scenario)


def test_memory_is_stored_for_every_member_separately_and_not_for_outsiders(run_db):
    async def scenario(maker):
        await add_characters(maker, TRIO)
        user_id, conv_id = await make_group(maker, ("amy", "bob"))
        provider = ScriptedProvider(extraction_json=ONE_MEMORY)

        async with maker() as s:
            await GroupConversationService(s, provider).send_message(conv_id, user_id, "I love Interstellar")

        async with maker() as s:
            memories = (await s.execute(select(CharacterMemory))).scalars().all()
            from app.models import Character

            by_id = {c.id: c.slug for c in (await s.execute(select(Character))).scalars()}

        assert sorted(by_id[m.character_id] for m in memories) == ["amy", "bob"]  # not cy
        assert all(m.user_id == user_id and m.source_kind == "group" for m in memories)
        assert all(m.source_conversation_id == conv_id for m in memories)

    run_db(scenario)


def test_a_character_prompt_never_contains_another_characters_memory(run_db):
    async def scenario(maker):
        await add_characters(maker, TRIO)
        user_id, conv_id = await make_group(maker, ("amy", "bob"))
        from app.models import Character
        from app.services.character_memory_service import CharacterMemoryService

        async with maker() as s:
            bob = (await s.execute(select(Character).where(Character.slug == "bob"))).scalar_one()
            await CharacterMemoryService(s).add_memory(
                user_id=user_id, character_id=bob.id, category="personal",
                content="CANARY-BOB-SECRET", importance=10, confidence=1.0, memory_key="canary",
            )
            await s.commit()

        provider = PromptLog()
        async with maker() as s:
            reply = await GroupConversationService(s, provider).send_message(conv_id, user_id, "Amy, hello")
        assert reply.speaker.name == "Amy"
        assert "CANARY-BOB-SECRET" not in provider.chat_prompts[-1]

        async with maker() as s:
            await GroupConversationService(s, provider).send_message(conv_id, user_id, "Bob, hello")
        assert "CANARY-BOB-SECRET" in provider.chat_prompts[-1]  # Bob does know it

    run_db(scenario)


def test_deletion_request_applies_to_every_member(run_db):
    async def scenario(maker):
        await add_characters(maker, TRIO)
        user_id, conv_id = await make_group(maker, ("amy", "bob"))
        async with maker() as s:
            await GroupConversationService(s, ScriptedProvider(extraction_json=ONE_MEMORY)).send_message(
                conv_id, user_id, "I love Interstellar"
            )
        delete = json.dumps({"memories": [{
            "operation": "delete", "memory_key": "favorite_movie", "category": "interest",
            "content": "x", "importance": 5, "confidence": 0.99, "is_long_term": True,
        }]})
        async with maker() as s:
            await GroupConversationService(s, ScriptedProvider(extraction_json=delete)).send_message(
                conv_id, user_id, "forget my favorite movie"
            )
        async with maker() as s:
            assert (await s.execute(select(CharacterMemory))).scalars().all() == []

    run_db(scenario)


def test_provider_failure_keeps_the_user_message(run_db):
    async def scenario(maker):
        await add_characters(maker, TRIO)
        user_id, conv_id = await make_group(maker)
        async with maker() as s:
            with pytest.raises(AIResponseError):
                await GroupConversationService(s, ScriptedProvider(fail=["chat"])).send_message(
                    conv_id, user_id, "hello"
                )
        async with maker() as s:
            rows = (await s.execute(select(Message))).scalars().all()
        assert [r.sender_type for r in rows] == ["user"]

    run_db(scenario)


def test_another_user_and_direct_chats_and_inactive_members_are_refused(run_db):
    async def scenario(maker):
        await add_characters(maker, TRIO)
        user_id, conv_id = await make_group(maker)
        other_id, _ = await make_group(maker, ("amy", "cy"), telegram_id=2002)
        async with maker() as s:
            ctx = await ChatSessionService(s, ScriptedProvider()).open_character_chat(user_id, "amy")
            direct_id = ctx.conversation_id

        service = lambda s: GroupConversationService(s, ScriptedProvider())  # noqa: E731
        async with maker() as s:
            with pytest.raises(ValueError):
                await service(s).send_message(conv_id, other_id, "hi")
        async with maker() as s:
            with pytest.raises(ValueError):
                await service(s).send_message(direct_id, user_id, "hi")

        from app.models import Character

        async with maker() as s:
            bob = (await s.execute(select(Character).where(Character.slug == "bob"))).scalar_one()
            bob.is_active = False
            await s.commit()
        async with maker() as s:
            with pytest.raises(ValueError):
                await service(s).send_message(conv_id, user_id, "hi")
            assert (await s.execute(select(Message).where(Message.conversation_id == conv_id))).scalars().all() == []

    run_db(scenario)


def test_continuation_and_labelled_summary(run_db):
    async def scenario(maker):
        await add_characters(maker, TRIO)
        user_id, conv_id = await make_group(maker)
        provider = PromptLog(chat_reply="ok")

        async with maker() as s:
            first = await GroupConversationService(s, provider).send_message(conv_id, user_id, "Bob, hi")
        async with maker() as s:
            second = await GroupConversationService(s, provider).send_message(conv_id, user_id, "and then?")
        assert (first.speaker.name, second.speaker.name, second.reason) == ("Bob", "Bob", "continuation")

        seen = []

        class Spy(PromptLog):
            async def generate_response(self, system_prompt, messages):
                if "long-term conversation memory manager" in system_prompt.lower():
                    seen.append(messages)
                return await super().generate_response(system_prompt, messages)

        spy = Spy(chat_reply="ok")
        for i in range(4):
            async with maker() as s:
                await GroupConversationService(s, spy).send_message(conv_id, user_id, f"Amy, n{i}")
        assert seen, "summary should have run"
        assert any("Bob: ok" in m["content"] or "Amy: ok" in m["content"] for m in seen[0])

    run_db(scenario)


# --------------------------------------------------------------- bot flow


def test_bot_answers_in_a_group_with_the_speakers_name(run_db, tmp_path):
    async def scenario(maker):
        await add_characters(maker, TRIO)
        provider = ScriptedProvider(chat_reply="<b>hi</b> there")
        bot = Harness(maker, tmp_path, provider)
        await bot.send(message_update("/newgroup"))
        await bot.send(callback_update("gsel:0:amy"))
        await bot.send(callback_update("gsel:0:bob"))
        await bot.send(callback_update("gdone"))

        await bot.send(message_update("Bob, hello"))
        last = bot.session.named("SendMessage")[-1]
        assert last["text"] == "<b>Bob:</b> &lt;b&gt;hi&lt;/b&gt; there"
        assert last["parse_mode"] == "HTML"

        await bot.send(message_update("/history"))
        await bot.send(callback_update("hopen:" + "x"))  # unknown id must not crash the bot

    run_db(scenario)
