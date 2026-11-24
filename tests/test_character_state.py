"""Relationships and moods: storage rules, privacy, prompt use, cleanup."""

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models import Character, CharacterEmotion, CharacterRelationship
from app.services.character_removal_service import CharacterRemovalService
from app.services.character_state_service import (
    DECAY_PER_HOUR,
    MAX_STEP,
    CharacterEmotionService,
    CharacterRelationshipService,
)
from app.services.group_context_builder import character_state_text
from app.services.group_conversation_service import GroupConversationService
from tests.test_group_messaging import TRIO, PromptLog, add_characters, make_group


async def ids(maker):
    async with maker() as s:
        return {c.slug: c.id for c in (await s.execute(select(Character))).scalars()}


class Row:
    def __init__(self, **kw):
        base = dict(trust=50, affection=50, respect=50, jealousy=0, rivalry=0, familiarity=0, tension=0)
        base.update(kw)
        self.__dict__.update(base)


# ------------------------------------------------------------ pure prompt text


def test_neutral_feelings_add_nothing():
    assert character_state_text(None, {"Bob": Row()}) == ""


def test_feelings_become_behaviour_hints_without_numbers():
    class E:
        mood, intensity, reason = "upset", 80, "Bob mocked her"

    out = character_state_text(E, {"Bob": Row(trust=20, tension=70, jealousy=40), "Cy": Row()})
    assert "strongly upset (Bob mocked her)" in out
    assert "do not reset your mood" in out and "Never mention scores" in out
    assert "About Bob:" in out and "you do not trust them" in out and "tense" in out and "jealous" in out
    assert "Cy" not in out
    assert not any(ch.isdigit() for ch in out.replace("YOUR FEELINGS (private)", ""))


# ---------------------------------------------------------------- relationships


def test_deltas_are_limited_clamped_and_filtered(run_db):
    async def scenario(maker):
        await add_characters(maker, TRIO)
        c = await ids(maker)
        user_id, _ = await make_group(maker)

        async with maker() as s:
            svc = CharacterRelationshipService(s)
            values = await svc.apply_deltas(
                user_id, c["amy"], c["bob"],
                {"trust": 99, "tension": -99, "affection": True, "bogus": 3, "respect": "x", "rivalry": 2},
            )
            await s.commit()

        assert values["trust"] == 50 + MAX_STEP  # one update moves a value only a little
        assert values["tension"] == 0  # never below 0
        assert values["affection"] == 50 and values["respect"] == 50  # junk ignored
        assert values["rivalry"] == 2

        async with maker() as s:
            svc = CharacterRelationshipService(s)
            for _ in range(30):
                await svc.apply_deltas(user_id, c["amy"], c["bob"], {"trust": 5})
            await s.commit()
            row = (await svc.get_for_speaker(user_id, c["amy"], [c["bob"]]))[c["bob"]]
        assert row.trust == 100  # never above 100

    run_db(scenario)


def test_relationships_are_directional_and_private_to_their_owner(run_db):
    async def scenario(maker):
        await add_characters(maker, TRIO)
        c = await ids(maker)
        user_id, _ = await make_group(maker)

        async with maker() as s:
            svc = CharacterRelationshipService(s)
            await svc.apply_deltas(user_id, c["amy"], c["bob"], {"trust": 5})
            await svc.apply_deltas(user_id, c["bob"], c["amy"], {"trust": -5})
            await svc.apply_deltas(user_id, c["bob"], c["cy"], {"trust": 5})  # Bob's view of Cy
            await s.commit()

            amy_view = await svc.get_for_speaker(user_id, c["amy"], [c["bob"], c["cy"]])
            bob_view = await svc.get_for_speaker(user_id, c["bob"], [c["amy"]])
            other_user = await svc.get_for_speaker(
                (await make_group(maker, telegram_id=2002))[0], c["amy"], [c["bob"]]
            )

        assert amy_view[c["bob"]].trust == 55 and bob_view[c["amy"]].trust == 45  # asymmetric
        assert set(amy_view) == {c["bob"]}  # Bob's feelings about Cy are not Amy's
        assert other_user == {}  # another user never sees it

    run_db(scenario)


def test_a_character_cannot_have_a_relationship_with_itself(run_db):
    async def scenario(maker):
        await add_characters(maker, TRIO)
        c = await ids(maker)
        user_id, _ = await make_group(maker)
        async with maker() as s:
            with pytest.raises(ValueError):
                await CharacterRelationshipService(s).apply_deltas(user_id, c["amy"], c["amy"], {"trust": 1})

    run_db(scenario)


# ---------------------------------------------------------------------- moods


def test_mood_persists_fades_and_is_validated(run_db):
    async def scenario(maker):
        await add_characters(maker, TRIO)
        c = await ids(maker)
        user_id, _ = await make_group(maker)

        async with maker() as s:
            svc = CharacterEmotionService(s)
            with pytest.raises(ValueError):
                await svc.set_emotion(user_id, c["amy"], "ecstatic-ish", 50)
            with pytest.raises(ValueError):
                await svc.set_emotion(user_id, c["amy"], "upset", "high")
            await svc.set_emotion(user_id, c["amy"], "upset", 500, "x" * 500)
            await s.commit()

            now = (await s.execute(select(CharacterEmotion.updated_at))).scalar_one()
            fresh = await svc.get_emotion(user_id, c["amy"], now=now)
            assert (fresh.mood, fresh.intensity) == ("upset", 100) and len(fresh.reason) == 200
            # Not reset by anything, only faded by time.
            later = await svc.get_emotion(user_id, c["amy"], now=now + timedelta(hours=3))
            assert later.intensity == 100 - 3 * DECAY_PER_HOUR
            assert await svc.get_emotion(user_id, c["amy"], now=now + timedelta(hours=20)) is None
            assert await svc.get_emotion(user_id, c["bob"], now=now) is None  # per character
            stranger_id, _ = await make_group(maker, telegram_id=3003)
            assert await svc.get_emotion(stranger_id, c["amy"], now=now) is None  # per user

            await svc.set_emotion(user_id, c["amy"], "calm", 40)  # update, not a duplicate
            await s.commit()
            rows = (await s.execute(select(CharacterEmotion))).scalars().all()
            assert len(rows) == 1 and rows[0].mood == "calm"

    run_db(scenario)


# --------------------------------------------------------- group prompt wiring


def test_only_the_speakers_own_feelings_reach_its_prompt(run_db):
    async def scenario(maker):
        await add_characters(maker, TRIO)
        c = await ids(maker)
        user_id, conv_id = await make_group(maker, ("amy", "bob"))

        async with maker() as s:
            rel = CharacterRelationshipService(s)
            for _ in range(8):
                await rel.apply_deltas(user_id, c["amy"], c["bob"], {"trust": -5, "tension": 5})
            await rel.apply_deltas(user_id, c["bob"], c["amy"], {"affection": 5})
            await CharacterEmotionService(s).set_emotion(user_id, c["bob"], "playful", 60, "BOB-ONLY-REASON")
            await s.commit()

        provider = PromptLog(chat_reply="hey")
        async with maker() as s:
            await GroupConversationService(s, provider).send_message(conv_id, user_id, "Amy, hi")
        amy_prompt = provider.chat_prompts[-1]
        assert "YOUR FEELINGS" in amy_prompt and "About Bob:" in amy_prompt and "you do not trust them" in amy_prompt
        assert "BOB-ONLY-REASON" not in amy_prompt and "playful" not in amy_prompt

        async with maker() as s:
            await GroupConversationService(s, provider).send_message(conv_id, user_id, "Bob, hi")
        bob_prompt = provider.chat_prompts[-1]
        assert "you are playful (BOB-ONLY-REASON)" in bob_prompt
        assert "do not trust" not in bob_prompt  # Amy's distrust of Bob is not Bob's feeling

    run_db(scenario)


def test_neutral_characters_get_no_feelings_section(run_db):
    async def scenario(maker):
        await add_characters(maker, TRIO)
        user_id, conv_id = await make_group(maker, ("amy", "bob"))
        provider = PromptLog(chat_reply="hey")
        async with maker() as s:
            await GroupConversationService(s, provider).send_message(conv_id, user_id, "Amy, hi")
        assert "YOUR FEELINGS" not in provider.chat_prompts[-1]

    run_db(scenario)


# -------------------------------------------------------------------- cleanup


def test_removing_a_character_removes_its_feelings_both_ways_for_that_user_only(run_db):
    async def scenario(maker):
        await add_characters(maker, TRIO)
        c = await ids(maker)
        user_id, _ = await make_group(maker, ("amy", "bob"))
        other_id, _ = await make_group(maker, ("amy", "bob"), telegram_id=2002)

        async with maker() as s:
            rel, emo = CharacterRelationshipService(s), CharacterEmotionService(s)
            for uid in (user_id, other_id):
                await rel.apply_deltas(uid, c["amy"], c["bob"], {"trust": 3})
                await rel.apply_deltas(uid, c["bob"], c["amy"], {"trust": 3})
                await rel.apply_deltas(uid, c["bob"], c["cy"], {"trust": 3})
                await emo.set_emotion(uid, c["amy"], "calm", 50)
                await emo.set_emotion(uid, c["bob"], "calm", 50)
            await s.commit()

        async with maker() as s:
            await CharacterRemovalService(s).remove(user_id, "amy")

        async with maker() as s:
            mine = (await s.execute(select(CharacterRelationship).where(CharacterRelationship.user_id == user_id))).scalars().all()
            assert [(r.character_id, r.other_character_id) for r in mine] == [(c["bob"], c["cy"])]
            emotions = (await s.execute(select(CharacterEmotion).where(CharacterEmotion.user_id == user_id))).scalars().all()
            assert [e.character_id for e in emotions] == [c["bob"]]
            theirs = (await s.execute(select(CharacterRelationship).where(CharacterRelationship.user_id == other_id))).scalars().all()
            assert len(theirs) == 3  # the other user's world is untouched
            assert len((await s.execute(select(CharacterEmotion).where(CharacterEmotion.user_id == other_id))).scalars().all()) == 2

    run_db(scenario)


def test_database_rejects_out_of_range_and_self_rows(run_db):
    async def scenario(maker):
        await add_characters(maker, TRIO)
        c = await ids(maker)
        user_id, _ = await make_group(maker)
        from sqlalchemy.exc import IntegrityError

        for kwargs in (
            dict(character_id=c["amy"], other_character_id=c["amy"]),
            dict(character_id=c["amy"], other_character_id=c["bob"], trust=101),
            dict(character_id=c["amy"], other_character_id=c["bob"], tension=-1),
        ):
            async with maker() as s:
                s.add(CharacterRelationship(user_id=user_id, **kwargs))
                with pytest.raises(IntegrityError):
                    await s.commit()

    run_db(scenario)
