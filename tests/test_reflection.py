"""Feelings reflection: batching, validation, atomicity, end-to-end effect."""

import json

import pytest
from sqlalchemy import select, update

from app.models import CharacterEmotion, CharacterRelationship, Conversation
from app.services import group_conversation_service as module
from app.services.group_conversation_service import GroupConversationService
from app.services.relationship_reflector import REFLECTOR_MARKER, RelationshipReflector
from tests.telegram_harness import Harness, callback_update, message_update
from tests.test_character_state import ids
from tests.test_group_messaging import AMY, BOB, TRIO, PromptLog, add_characters, make_group

GOOD = json.dumps(
    {
        "relationships": [{"from": "amy", "to": "bob", "trust": -3, "tension": 4}],
        "moods": [{"character": "bob", "mood": "upset", "intensity": 80, "reason": "Amy teased him"}],
    }
)


class ReflectProvider(PromptLog):
    def __init__(self, reflection_reply=GOOD, fails=False, on_call=None, **kw):
        super().__init__(**kw)
        self.reflection_reply = reflection_reply
        self.fails = fails
        self.on_call = on_call
        self.reflection_calls = 0
        self.reflection_input = ""

    async def generate_response(self, system_prompt, messages):
        if REFLECTOR_MARKER in system_prompt.lower():
            self.reflection_calls += 1
            self.reflection_input = messages[0]["content"]
            if self.on_call:
                await self.on_call()
            if self.fails:
                raise RuntimeError("down")
            return self.reflection_reply
        return await super().generate_response(system_prompt, messages)


@pytest.fixture(autouse=True)
def small_batches(monkeypatch):
    monkeypatch.setattr(module, "REFLECTION_MIN_NEW_MESSAGES", 2)


async def talk(maker, provider, text="Amy, hello", conv=None, reflection=True):
    if conv is None:
        await add_characters(maker, TRIO)
        user_id, conv_id = await make_group(maker, ("amy", "bob"))
    else:
        user_id, conv_id = conv
    async with maker() as s:
        await GroupConversationService(s, provider, reflection=reflection).send_message(conv_id, user_id, text)
    return user_id, conv_id


async def counter(maker, conv_id):
    async with maker() as s:
        return (await s.get(Conversation, conv_id)).reflection_message_count


# ---------------------------------------------------------------- validation


@pytest.mark.parametrize(
    "raw, rel, mood",
    [
        (GOOD, 1, 1),
        ('```json\n' + GOOD + '\n```', 1, 1),
        ('{"relationships": [], "moods": []}', 0, 0),
        ('{"relationships": [{"from": "amy", "to": "amy", "trust": 1}], "moods": []}', 0, 0),
        ('{"relationships": [{"from": "amy", "to": "ghost", "trust": 1}], "moods": []}', 0, 0),
        ('{"relationships": [{"from": "amy", "to": "bob", "bogus": 1, "trust": "x", "rivalry": true}], "moods": []}', 0, 0),
        ('{"relationships": "x", "moods": {"a": 1}}', 0, 0),
        ('{"relationships": [], "moods": [{"character": "bob", "mood": "ecstatic", "intensity": 5}]}', 0, 0),
        ('{"relationships": [], "moods": [{"character": "bob", "mood": "sad", "intensity": "5"}]}', 0, 0),
        ('{"relationships": [], "moods": [{"character": "ghost", "mood": "sad", "intensity": 5}]}', 0, 0),
    ],
)
def test_reflection_output_is_validated(raw, rel, mood):
    result = RelationshipReflector._parse(raw, [AMY, BOB])
    assert result is not None and (len(result[0]), len(result[1])) == (rel, mood)


@pytest.mark.parametrize("raw", ["nonsense", "", None, "[]", '"x"'])
def test_unusable_reflection_output_is_none(raw):
    assert RelationshipReflector._parse(raw, [AMY, BOB]) is None


def test_entry_counts_are_capped():
    many = json.dumps({"relationships": [{"from": "amy", "to": "bob", "trust": 1}] * 50, "moods": [{"character": "bob", "mood": "sad", "intensity": 5}] * 50})
    rel, mood = RelationshipReflector._parse(many, [AMY, BOB])
    assert len(rel) == 12 and len(mood) == 4


# ------------------------------------------------------------------- behaviour


def test_feelings_are_updated_clamped_and_reach_the_next_prompt(run_db):
    async def scenario(maker):
        provider = ReflectProvider(
            json.dumps(
                {
                    "relationships": [{"from": "amy", "to": "bob", "trust": 99, "tension": -99}],
                    "moods": [{"character": "bob", "mood": "upset", "intensity": 80, "reason": "Amy teased him"}],
                }
            ),
            chat_reply="hey",
        )
        user_id, conv_id = await talk(maker, provider)
        c = await ids(maker)

        assert provider.reflection_calls == 1
        assert "Ada: Amy, hello" in provider.reflection_input and "Amy: hey" in provider.reflection_input
        async with maker() as s:
            rel = (await s.execute(select(CharacterRelationship))).scalar_one()
            assert (rel.character_id, rel.other_character_id) == (c["amy"], c["bob"])
            assert rel.trust == 55 and rel.tension == 0  # +-5 at most, one direction only
            mood = (await s.execute(select(CharacterEmotion))).scalar_one()
            assert (mood.character_id, mood.mood, mood.intensity) == (c["bob"], "upset", 80)
        assert await counter(maker, conv_id) == 2

        # Bob's next answer is shaped by his mood, Amy's is not.
        await talk(maker, provider, "Bob, you ok?", conv=(user_id, conv_id))
        assert "strongly upset (Amy teased him)" in provider.chat_prompts[-1]
        await talk(maker, provider, "Amy, you ok?", conv=(user_id, conv_id))
        assert "upset" not in provider.chat_prompts[-1]

    run_db(scenario)


def test_it_waits_for_enough_new_messages_and_is_off_by_default(run_db, monkeypatch):
    async def scenario(maker):
        monkeypatch.setattr(module, "REFLECTION_MIN_NEW_MESSAGES", 6)
        provider = ReflectProvider(chat_reply="hey")
        user_id, conv_id = await talk(maker, provider)  # 2 messages
        await talk(maker, provider, conv=(user_id, conv_id))  # 4
        assert provider.reflection_calls == 0 and await counter(maker, conv_id) == 0
        await talk(maker, provider, conv=(user_id, conv_id))  # 6
        assert provider.reflection_calls == 1 and await counter(maker, conv_id) == 6
        await talk(maker, provider, conv=(user_id, conv_id))  # 8: only 2 new
        assert provider.reflection_calls == 1

    run_db(scenario)

    async def disabled(maker):
        provider = ReflectProvider(chat_reply="hey")
        await talk(maker, provider, reflection=False)
        assert provider.reflection_calls == 0

    run_db(disabled)


def test_unusable_output_changes_nothing_but_is_not_paid_for_again(run_db):
    async def scenario(maker):
        provider = ReflectProvider("nonsense", chat_reply="hey")
        user_id, conv_id = await talk(maker, provider)
        assert provider.reflection_calls == 1 and await counter(maker, conv_id) == 2
        async with maker() as s:
            assert (await s.execute(select(CharacterRelationship))).scalars().all() == []
        await talk(maker, provider, conv=(user_id, conv_id))
        assert provider.reflection_calls == 2  # new batch of 2, not a retry of the old one
        assert "Ada: Amy, hello" in provider.reflection_input

    run_db(scenario)


def test_a_provider_error_is_retried_later_and_never_breaks_the_chat(run_db):
    async def scenario(maker):
        provider = ReflectProvider(fails=True, chat_reply="hey")
        user_id, conv_id = await talk(maker, provider)
        assert provider.reflection_calls == 1 and await counter(maker, conv_id) == 0
        async with maker() as s:
            assert (await s.execute(select(CharacterEmotion))).scalars().all() == []

        provider.fails = False
        await talk(maker, provider, conv=(user_id, conv_id))
        assert await counter(maker, conv_id) == 4  # the earlier messages are included now
        async with maker() as s:
            assert len((await s.execute(select(CharacterEmotion))).scalars().all()) == 1

    run_db(scenario)


def test_a_concurrent_request_cannot_apply_the_same_batch_twice(run_db):
    async def scenario(maker):
        state = {}

        async def other_request_wins():
            async with maker() as s:
                await s.execute(
                    update(Conversation)
                    .where(Conversation.id == state["conv"])
                    .values(reflection_message_count=2)
                )
                await s.commit()

        provider = ReflectProvider(chat_reply="hey", on_call=other_request_wins)
        await add_characters(maker, TRIO)
        user_id, conv_id = await make_group(maker, ("amy", "bob"))
        state["conv"] = conv_id
        await talk(maker, provider, conv=(user_id, conv_id))

        assert provider.reflection_calls == 1
        async with maker() as s:
            assert (await s.execute(select(CharacterRelationship))).scalars().all() == []
            assert (await s.execute(select(CharacterEmotion))).scalars().all() == []

    run_db(scenario)


def test_telegram_flow_runs_the_reflection(run_db, tmp_path):
    async def scenario(maker):
        await add_characters(maker, TRIO)
        provider = ReflectProvider(chat_reply="hey")
        bot = Harness(maker, tmp_path, provider)
        await bot.send(message_update("/newgroup"))
        await bot.send(callback_update("gsel:0:amy"))
        await bot.send(callback_update("gsel:0:bob"))
        await bot.send(callback_update("gdone"))
        await bot.send(message_update("Amy, hello"))

        assert provider.reflection_calls == 1
        async with maker() as s:
            assert (await s.execute(select(CharacterEmotion))).scalar_one().mood == "upset"

    run_db(scenario)


def test_only_the_new_messages_are_sent_to_the_reflection(run_db):
    async def scenario(maker):
        provider = ReflectProvider(chat_reply="hey")
        user_id, conv_id = await talk(maker, provider, "Amy, FIRSTBATCH")
        assert "FIRSTBATCH" in provider.reflection_input

        await talk(maker, provider, "Amy, SECONDBATCH", conv=(user_id, conv_id))
        assert provider.reflection_calls == 2
        assert "SECONDBATCH" in provider.reflection_input
        assert "FIRSTBATCH" not in provider.reflection_input

    run_db(scenario)


def test_a_boolean_intensity_is_dropped_so_it_cannot_abort_the_whole_update():
    raw = json.dumps(
        {
            "relationships": [],
            "moods": [
                {"character": "bob", "mood": "sad", "intensity": True},
                {"character": "amy", "mood": "calm", "intensity": 30},
            ],
        }
    )
    _, moods = RelationshipReflector._parse(raw, [AMY, BOB])
    assert [(m.slug, mood, intensity) for m, mood, intensity, _ in moods] == [("amy", "calm", 30)]
