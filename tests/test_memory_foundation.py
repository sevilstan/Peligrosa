"""Memory foundation: new categories, provenance, relevance-aware recall.

Memory stays per user + character; these tests also pin down that no new path
can leak one character's or one user's memories to another.
"""

import pytest
from sqlalchemy import delete, select

from app.models import Character, CharacterMemory, Conversation, User
from app.services.character_memory_service import CharacterMemoryService, topic_terms
from app.services.conversation_service import MEMORY_LIMIT, ConversationService
from app.services.memory_extractor import MemoryExtractor
from tests.test_conversation_engine import ScriptedProvider, seed_conversation

EVENT_JSON = """
{"memories": [{
    "operation": "upsert",
    "memory_key": "event_osman_new_job",
    "category": "event",
    "content": "Osman got a new job.",
    "importance": 7,
    "confidence": 0.9,
    "is_long_term": true
}]}
"""

RELATIONSHIP_JSON = """
{"memories": [{
    "operation": "upsert",
    "memory_key": "relationship_osman",
    "category": "relationship",
    "content": "Osman is the user's older brother.",
    "importance": 8,
    "confidence": 0.95,
    "is_long_term": true
}]}
"""


# ------------------------------------------------------------ topic terms


def test_topic_terms_keep_meaningful_words_only():
    terms = topic_terms("How is Osman's new job? The user said hello, 2024!")

    assert "osman" in terms
    assert "user" not in terms and "job" not in terms  # stop word / too short
    assert all(t == t.lower() and t.isalpha() for t in terms)


def test_topic_terms_handle_turkish_stems_and_limits():
    terms = topic_terms("filmleri çok sevdim")  # "çok" is too short/common

    assert "filmleri" in terms and "filml" in terms  # stem finds "film..."
    assert "çok" not in terms
    assert len(topic_terms(" ".join(f"word{chr(97 + i)}x" * 1 for i in range(20)))) <= 16


@pytest.mark.parametrize("text", [None, "", "   ", "a an of", "123 456 !!!"])
def test_topic_terms_of_nothing_is_empty(text):
    assert topic_terms(text) == []


# ------------------------------------------------------------ categories


@pytest.mark.parametrize(
    "payload, category",
    [(EVENT_JSON, "event"), (RELATIONSHIP_JSON, "relationship")],
)
def test_extractor_accepts_event_and_relationship(payload, category):
    import asyncio

    extractor = MemoryExtractor(ai_provider=ScriptedProvider(extraction_json=payload))

    result = asyncio.run(extractor.extract("Osman got a new job."))

    assert [m["category"] for m in result] == [category]


def test_extractor_still_rejects_unknown_categories_and_keeps_safeguards():
    import asyncio

    bad = EVENT_JSON.replace('"event"', '"gossip"')
    extractor = MemoryExtractor(ai_provider=ScriptedProvider(extraction_json=bad))

    assert asyncio.run(extractor.extract("Osman got a job.")) == []
    # deletion safeguards are untouched
    assert MemoryExtractor.is_explicit_deletion_request("Forget my favorite movie.")
    assert not MemoryExtractor.is_explicit_deletion_request("Don't delete that memory.")


# ------------------------------------------------------------ provenance


def test_new_memories_from_a_chat_record_where_they_were_learned(run_db):
    async def scenario(maker):
        uid, cid, conv = await seed_conversation(maker)
        provider = ScriptedProvider(extraction_json=EVENT_JSON)

        async with maker() as s:
            await ConversationService(s, ai_provider=provider).send_message(conv, uid, "Osman got a new job!")

        async with maker() as s:
            memory = (await s.execute(select(CharacterMemory))).scalar_one()

        assert (memory.category, memory.source_kind, memory.source_conversation_id) == ("event", "direct", conv)

    run_db(scenario)


def test_provenance_follows_the_latest_telling_and_survives_chat_deletion(run_db):
    async def scenario(maker):
        uid, cid, conv = await seed_conversation(maker)

        async with maker() as s:
            service = CharacterMemoryService(s)
            first = await service.add_memory(uid, cid, "event", "Osman got a job.", memory_key="event_osman")
            assert (first.source_kind, first.source_conversation_id) == (None, None)

            await service.add_memory(uid, cid, "event", "Osman got a job.", memory_key="event_osman",
                                     source_conversation_id=conv, source_kind="direct")
            await s.commit()

        async with maker() as s:
            await s.execute(delete(Conversation).where(Conversation.id == conv))
            await s.commit()

        async with maker() as s:
            memory = (await s.execute(select(CharacterMemory))).scalar_one()
        assert memory.content == "Osman got a job."  # the memory outlives its chat
        assert memory.source_conversation_id is None and memory.source_kind == "direct"

    run_db(scenario)


def test_database_refuses_an_unknown_source_kind(run_db):
    from sqlalchemy.exc import IntegrityError

    async def scenario(maker):
        uid, cid, _ = await seed_conversation(maker)

        async with maker() as s:
            s.add(CharacterMemory(user_id=uid, character_id=cid, category="event",
                                  content="x", source_kind="telepathy"))
            with pytest.raises(IntegrityError):
                await s.commit()

    run_db(scenario)


# -------------------------------------------------------- relevant recall


async def fill(maker, uid, cid, important=10, extra=()):
    """`important` high-importance filler memories plus (key, text, importance) extras."""
    async with maker() as s:
        service = CharacterMemoryService(s)
        for i in range(important):
            await service.add_memory(uid, cid, "interest", f"Filler fact number {i}.",
                                     importance=9, memory_key=f"filler_{i}")
        for key, text, importance in extra:
            await service.add_memory(uid, cid, "event", text, importance=importance, memory_key=key)
        await s.commit()


def contents(memories):
    return [m.content for m in memories]


def test_a_low_importance_memory_is_recalled_when_it_is_the_topic(run_db):
    async def scenario(maker):
        uid, cid, _ = await seed_conversation(maker)
        await fill(maker, uid, cid, extra=[("event_osman_new_job", "Osman got a new job.", 2)])

        async with maker() as s:
            service = CharacterMemoryService(s)
            quiet = await service.get_relevant_memories(uid, cid, "What should we watch tonight?", MEMORY_LIMIT)
            asked = await service.get_relevant_memories(uid, cid, "How is Osman doing these days?", MEMORY_LIMIT)
            no_context = await service.get_relevant_memories(uid, cid, None, MEMORY_LIMIT)

        assert "Osman got a new job." not in contents(quiet)
        assert "Osman got a new job." in contents(asked)
        assert contents(no_context) == contents(quiet)
        assert len(quiet) == len(asked) == MEMORY_LIMIT  # the prompt does not grow

    run_db(scenario)


def test_recall_keeps_the_most_important_memories_and_a_hard_limit(run_db):
    async def scenario(maker):
        uid, cid, _ = await seed_conversation(maker)
        extras = [(f"event_osman_{i}", f"Osman did thing {i}.", 1 + i % 3) for i in range(15)]
        await fill(maker, uid, cid, extra=extras)

        async with maker() as s:
            service = CharacterMemoryService(s)
            top = await service.get_memories(uid, cid, limit=MEMORY_LIMIT)
            recalled = await service.get_relevant_memories(uid, cid, "Tell me about Osman", MEMORY_LIMIT)

        assert len(recalled) == MEMORY_LIMIT
        assert contents(recalled[: MEMORY_LIMIT // 2]) == contents(top[: MEMORY_LIMIT // 2])
        assert sum("Osman" in c for c in contents(recalled)) == MEMORY_LIMIT - MEMORY_LIMIT // 2
        # matches are chosen by importance, not randomly
        matched = [m for m in recalled if "Osman" in m.content]
        assert [m.importance for m in matched] == sorted((m.importance for m in matched), reverse=True)

    run_db(scenario)


def test_recall_never_crosses_characters_or_users(run_db):
    async def scenario(maker):
        uid, cid, _ = await seed_conversation(maker)
        async with maker() as s:
            other_user = User(email="other@example.test", language_code="en")
            other_char = Character(name="Other", slug="other", description="d", personality="p", system_prompt="s")
            s.add_all([other_user, other_char])
            await s.commit()
            other_user_id, other_char_id = other_user.id, other_char.id

        await fill(maker, uid, cid)
        await fill(maker, uid, other_char_id, important=0,
                   extra=[("event_osman_secret", "OSMAN-SECRET of another character.", 10)])
        await fill(maker, other_user_id, cid, important=0,
                   extra=[("event_osman_other", "OSMAN-SECRET of another user.", 10)])

        async with maker() as s:
            recalled = await CharacterMemoryService(s).get_relevant_memories(
                uid, cid, "Osman Osman Osman", MEMORY_LIMIT)

        assert not any("SECRET" in c for c in contents(recalled))

    run_db(scenario)


def test_search_text_cannot_act_as_a_wildcard(run_db):
    async def scenario(maker):
        uid, cid, _ = await seed_conversation(maker)
        await fill(maker, uid, cid, extra=[("event_x", "Plain unrelated fact.", 1)])

        async with maker() as s:
            recalled = await CharacterMemoryService(s).get_relevant_memories(
                uid, cid, "100% _____ %%%% ''; DROP TABLE users; --", MEMORY_LIMIT)

        assert "Plain unrelated fact." not in contents(recalled)

    run_db(scenario)


def test_the_chat_prompt_contains_the_recalled_memory_when_it_is_the_topic(run_db):
    async def scenario(maker):
        uid, cid, conv = await seed_conversation(maker)
        await fill(maker, uid, cid, extra=[("event_osman_new_job", "Osman got a new job.", 2)])
        provider = ScriptedProvider()

        async with maker() as s:
            await ConversationService(s, ai_provider=provider).send_message(conv, uid, "Any news about Osman?")
        assert "Osman got a new job." in provider.last_chat_prompt

        # the topic carries over to the next message of the same chat...
        async with maker() as s:
            await ConversationService(s, ai_provider=provider).send_message(conv, uid, "What shall we cook?")
        assert "Osman got a new job." in provider.last_chat_prompt

        # ...but a fresh chat about something else does not recall it.
        async with maker() as s:
            fresh = await ConversationService(s, ai_provider=provider).create_conversation(uid, cid)
            fresh_id = fresh.id
        async with maker() as s:
            await ConversationService(s, ai_provider=provider).send_message(fresh_id, uid, "What shall we cook?")
        assert "Osman got a new job." not in provider.last_chat_prompt

    run_db(scenario)
