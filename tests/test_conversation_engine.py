"""Conversation engine behaviour: failures, privacy of logs, concurrency.

These need a disposable database (see tests/conftest.py).
"""

import logging
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.models import (
    Character,
    CharacterMemory,
    Conversation,
    Message,
    User,
)
from app.services.character_memory_service import CharacterMemoryService
from app.services.conversation_service import AIResponseError, ConversationService

EXTRACTION_MARKER = "long-term memory extraction system"
SUMMARY_MARKER = "long-term conversation memory manager"

NO_MEMORIES = '{"memories": []}'
ONE_MEMORY = """
{"memories": [{
    "operation": "upsert",
    "memory_key": "favorite_movie",
    "category": "interest",
    "content": "Interstellar is the user's favorite movie.",
    "importance": 9,
    "confidence": 0.98,
    "is_long_term": true
}]}
"""


class ScriptedProvider:
    """Fake AI provider that answers by kind of request and can fail on demand."""

    def __init__(self, chat_reply="Merhaba!", extraction_json=NO_MEMORIES, fail=()):
        self.chat_reply = chat_reply
        self.extraction_json = extraction_json
        self.fail = set(fail)
        self.summaries = 0
        self.last_chat_prompt = ""

    async def generate_response(self, system_prompt, messages):
        low = system_prompt.lower()

        if EXTRACTION_MARKER in low:
            kind = "extraction"
        elif SUMMARY_MARKER in low:
            kind = "summary"
        else:
            kind = "chat"

        if kind in self.fail:
            raise RuntimeError(f"{kind} provider is down")

        if kind == "extraction":
            return self.extraction_json

        if kind == "summary":
            self.summaries += 1
            return f"summary-{self.summaries}"

        self.last_chat_prompt = system_prompt
        return self.chat_reply


# "test-char" has no YAML file, so the character's database fields are used.
async def seed_conversation(maker, slug="test-char", email="user@example.test"):
    async with maker() as session:
        user = User(email=email, language_code="tr")
        character = Character(
            name="Testa",
            slug=slug,
            description="A test character.",
            personality="Calm.",
            system_prompt="You are Testa.",
        )
        session.add_all([user, character])
        await session.commit()

        service = ConversationService(session, ai_provider=ScriptedProvider())
        conversation = await service.create_conversation(user.id, character.id)

        return user.id, character.id, conversation.id


async def add_messages(maker, conversation_id, user_id, character_id, count):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)

    async with maker() as session:
        for index in range(count):
            from_user = index % 2 == 0
            session.add(
                Message(
                    conversation_id=conversation_id,
                    sender_type="user" if from_user else "character",
                    sender_user_id=user_id if from_user else None,
                    sender_character_id=None if from_user else character_id,
                    content=f"message {index}",
                    message_type="text",
                    created_at=start + timedelta(minutes=index),
                )
            )
        await session.commit()


async def count_messages(maker, conversation_id, sender_type):
    async with maker() as session:
        return await session.scalar(
            select(func.count())
            .select_from(Message)
            .where(
                Message.conversation_id == conversation_id,
                Message.sender_type == sender_type,
            )
        )


def test_normal_message_saves_reply_and_character_memory(run_db):
    async def scenario(maker):
        user_id, character_id, conversation_id = await seed_conversation(maker)
        provider = ScriptedProvider(extraction_json=ONE_MEMORY)

        async with maker() as session:
            service = ConversationService(session, ai_provider=provider)
            reply = await service.send_message(conversation_id, user_id, "Interstellar favorim.")

            assert reply.content == "Merhaba!"
            assert "Interstellar" in provider.last_chat_prompt

        assert await count_messages(maker, conversation_id, "user") == 1
        assert await count_messages(maker, conversation_id, "character") == 1

    run_db(scenario)


def test_provider_failure_keeps_user_message_and_raises_ai_response_error(run_db):
    async def scenario(maker):
        user_id, _, conversation_id = await seed_conversation(maker)

        async with maker() as session:
            service = ConversationService(session, ai_provider=ScriptedProvider(fail={"chat"}))

            with pytest.raises(AIResponseError):
                await service.send_message(conversation_id, user_id, "Merhaba")

            # The session must still be usable after the failure.
            assert await session.scalar(select(func.count()).select_from(Message)) == 1

        assert await count_messages(maker, conversation_id, "user") == 1
        assert await count_messages(maker, conversation_id, "character") == 0

    run_db(scenario)


def test_empty_reply_is_an_error_and_is_not_saved(run_db):
    async def scenario(maker):
        user_id, _, conversation_id = await seed_conversation(maker)

        async with maker() as session:
            service = ConversationService(session, ai_provider=ScriptedProvider(chat_reply="   "))

            with pytest.raises(AIResponseError):
                await service.send_message(conversation_id, user_id, "Merhaba")

        assert await count_messages(maker, conversation_id, "character") == 0

    run_db(scenario)


def test_memory_extraction_failure_does_not_block_the_reply(run_db):
    async def scenario(maker):
        user_id, _, conversation_id = await seed_conversation(maker)

        async with maker() as session:
            service = ConversationService(
                session, ai_provider=ScriptedProvider(fail={"extraction"})
            )
            reply = await service.send_message(conversation_id, user_id, "Merhaba")

            assert reply.content == "Merhaba!"

    run_db(scenario)


def test_memory_write_failure_does_not_block_reply_or_leak_text_to_logs(
    run_db, monkeypatch, caplog
):
    async def broken_add_memory(self, **kwargs):
        raise RuntimeError("TOP-SECRET-USER-TEXT")

    monkeypatch.setattr(CharacterMemoryService, "add_memory", broken_add_memory)
    caplog.set_level(logging.INFO)

    async def scenario(maker):
        user_id, _, conversation_id = await seed_conversation(maker)

        async with maker() as session:
            service = ConversationService(
                session, ai_provider=ScriptedProvider(extraction_json=ONE_MEMORY)
            )
            reply = await service.send_message(conversation_id, user_id, "Interstellar favorim.")

            # The returned object must still be readable after the rollback.
            assert reply.content == "Merhaba!"

            memories = await session.scalar(select(func.count()).select_from(CharacterMemory))
            assert memories == 0

    run_db(scenario)

    assert "Memory update failed" in caplog.text
    assert "TOP-SECRET-USER-TEXT" not in caplog.text


def test_summary_is_created_once_enough_messages_exist(run_db):
    async def scenario(maker):
        user_id, character_id, conversation_id = await seed_conversation(maker)
        await add_messages(maker, conversation_id, user_id, character_id, 12)

        async with maker() as session:
            service = ConversationService(session, ai_provider=ScriptedProvider())
            await service.send_message(conversation_id, user_id, "Merhaba")

        async with maker() as session:
            conversation = await session.get(Conversation, conversation_id)
            assert conversation.summary == "summary-1"
            assert conversation.summary_message_count == 14

    run_db(scenario)


def test_summary_failure_does_not_break_the_reply(run_db):
    async def scenario(maker):
        user_id, character_id, conversation_id = await seed_conversation(maker)
        await add_messages(maker, conversation_id, user_id, character_id, 12)

        async with maker() as session:
            service = ConversationService(session, ai_provider=ScriptedProvider(fail={"summary"}))
            reply = await service.send_message(conversation_id, user_id, "Merhaba")

            assert reply.content == "Merhaba!"

        async with maker() as session:
            conversation = await session.get(Conversation, conversation_id)
            assert conversation.summary is None
            assert conversation.summary_message_count == 0

    run_db(scenario)


def test_concurrent_summary_updates_apply_only_once(run_db):
    async def scenario(maker):
        user_id, character_id, conversation_id = await seed_conversation(maker)
        await add_messages(maker, conversation_id, user_id, character_id, 12)

        provider = ScriptedProvider()

        async with maker() as first_session, maker() as second_session:
            first = await first_session.get(Conversation, conversation_id)
            second = await second_session.get(Conversation, conversation_id)

            await ConversationService(first_session, ai_provider=provider).update_conversation_summary(first)
            # `second` still believes nothing was summarized yet.
            await ConversationService(second_session, ai_provider=provider).update_conversation_summary(second)

            assert second.summary == "summary-1"

        async with maker() as session:
            conversation = await session.get(Conversation, conversation_id)
            assert conversation.summary == "summary-1"
            assert conversation.summary_message_count == 12

        # The loser did call the summarizer but its result was discarded.
        assert provider.summaries == 2

    run_db(scenario)


def test_system_prompt_only_contains_this_characters_memories_for_this_user(run_db):
    async def scenario(maker):
        user_id, character_id, conversation_id = await seed_conversation(maker)

        async with maker() as session:
            other_user = User(email="other@example.test", language_code="en")
            other_character = Character(
                name="Other",
                slug="other-char",
                description="d",
                personality="p",
                system_prompt="You are Other.",
            )
            session.add_all([other_user, other_character])
            await session.flush()

            session.add_all(
                [
                    CharacterMemory(
                        user_id=user_id, character_id=character_id, category="interest",
                        memory_key="own", content="OWN-MEMORY",
                    ),
                    CharacterMemory(
                        user_id=user_id, character_id=other_character.id, category="interest",
                        memory_key="other_character", content="OTHER-CHARACTER-MEMORY",
                    ),
                    CharacterMemory(
                        user_id=other_user.id, character_id=character_id, category="interest",
                        memory_key="other_user", content="OTHER-USER-MEMORY",
                    ),
                ]
            )
            await session.commit()

            conversation = await session.get(Conversation, conversation_id)
            character = await session.get(Character, character_id)
            service = ConversationService(session, ai_provider=ScriptedProvider())

            prompt = await service.build_system_prompt(conversation, character, user_id)

            assert "OWN-MEMORY" in prompt
            assert "OTHER-CHARACTER-MEMORY" not in prompt
            assert "OTHER-USER-MEMORY" not in prompt

    run_db(scenario)
