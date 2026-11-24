"""Characters writing first: every rule, and nothing leaks between users."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models import Character, CharacterMemory, Message, User
from app.services.chat_session_service import ChatSessionService
from app.services.initiative_service import (
    INITIATIVE_MESSAGE_TYPE,
    InitiativeConfig,
    InitiativeService,
    in_quiet_hours,
)
from app.services.telegram_user_service import TelegramUserService
from tests.test_character_state import ids
from tests.test_conversation_engine import ScriptedProvider
from tests.test_group_messaging import TRIO, PromptLog, add_characters

NEVER_QUIET = InitiativeConfig(quiet_start_hour=0, quiet_end_hour=0)
ALWAYS_QUIET = InitiativeConfig(quiet_start_hour=0, quiet_end_hour=24)


def hours(n):
    return datetime.now(timezone.utc) + timedelta(hours=n)


async def make_user(maker, telegram_id=1001, opted_in=True, **fields):
    async with maker() as s:
        user = await TelegramUserService(s).get_or_create(telegram_id, "Ada")
        user.proactive_enabled = opted_in
        for key, value in fields.items():
            setattr(user, key, value)
        await s.commit()
        return user.id


async def direct_chat(maker, user_id, slug="amy", say="hello"):
    """A direct chat with one exchange; returns the conversation id."""
    async with maker() as s:
        ctx = await ChatSessionService(s, ScriptedProvider()).open_character_chat(user_id, slug)
        s.add(Message(conversation_id=ctx.conversation_id, sender_type="user", sender_user_id=user_id, content=say, message_type="text"))
        await s.commit()
        return ctx.conversation_id


async def attempt(maker, user_id, now, provider=None, config=NEVER_QUIET, rng=None):
    async with maker() as s:
        user = await s.get(User, user_id)
        service = InitiativeService(s, provider or PromptLog(chat_reply="Hey, how was your day?"), config, **({"rng": rng} if rng else {}))
        return await service.run_for_user(user, now)


async def initiatives(maker):
    async with maker() as s:
        rows = (await s.execute(select(Message).where(Message.message_type == INITIATIVE_MESSAGE_TYPE).order_by(Message.created_at))).scalars().all()
        return [(r.conversation_id, r.sender_type, r.sender_character_id, r.content) for r in rows]


# ------------------------------------------------------------------ quiet hours


@pytest.mark.parametrize(
    "hour_utc, offset, expected",
    [(19, 3, True), (20, 3, True), (5, 3, True), (6, 3, False), (7, 3, False), (18, 3, False), (21, 0, False), (22, 0, True), (3, 0, True), (8, 0, True), (9, 0, False)],
)
def test_quiet_hours_cross_midnight_and_follow_the_offset(hour_utc, offset, expected):
    config = InitiativeConfig(quiet_start_hour=22, quiet_end_hour=9, utc_offset_hours=offset)
    now = datetime(2026, 11, 24, hour_utc, 30, tzinfo=timezone.utc)
    assert in_quiet_hours(now, config) is expected


def test_quiet_hours_same_day_window_and_disabled_window():
    now = datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc)
    assert in_quiet_hours(now, InitiativeConfig(quiet_start_hour=9, quiet_end_hour=17, utc_offset_hours=0)) is True
    assert in_quiet_hours(now, InitiativeConfig(quiet_start_hour=5, quiet_end_hour=5, utc_offset_hours=0)) is False
    window = InitiativeConfig(quiet_start_hour=9, quiet_end_hour=17, utc_offset_hours=0)
    at = lambda hour: datetime(2026, 11, 24, hour, 0, tzinfo=timezone.utc)  # noqa: E731
    assert [in_quiet_hours(at(h), window) for h in (8, 9, 16, 17)] == [False, True, True, False]


# ------------------------------------------------------------------- direct chat


def test_a_character_writes_first_in_the_active_direct_chat(run_db):
    async def scenario(maker):
        await add_characters(maker, TRIO)
        c = await ids(maker)
        user_id = await make_user(maker)
        conv_id = await direct_chat(maker, user_id)
        async with maker() as s:
            from app.services.character_memory_service import CharacterMemoryService

            await CharacterMemoryService(s).add_memory(
                user_id=user_id, character_id=c["amy"], category="personal",
                content="Has an exam on Friday", importance=9, confidence=0.9, memory_key="exam",
            )
            await s.commit()

        provider = PromptLog(chat_reply="Hey, how did the exam prep go?")
        result = await attempt(maker, user_id, hours(7), provider)

        assert (result.conversation_id, result.is_group, result.speaker_name, result.content) == (conv_id, False, "Amy", "Hey, how did the exam prep go?")
        assert await initiatives(maker) == [(conv_id, "character", c["amy"], "Hey, how did the exam prep go?")]
        prompt = provider.chat_prompts[-1]
        assert "RIGHT NOW" in prompt and "Has an exam on Friday" in prompt
        assert provider.chat_messages[-1][-1]["role"] == "user"  # the model has a turn to answer

    run_db(scenario)


@pytest.mark.parametrize(
    "case",
    ["not_opted_in", "inactive", "quiet", "too_recent", "too_old"],
)
def test_no_initiative_when_a_rule_forbids_it(run_db, case):
    async def scenario(maker):
        await add_characters(maker, TRIO)
        user_id = await make_user(maker, opted_in=case != "not_opted_in", is_active=case != "inactive")
        await direct_chat(maker, user_id)
        now = {"too_recent": hours(2), "too_old": hours(24 * 8)}.get(case, hours(7))
        config = ALWAYS_QUIET if case == "quiet" else NEVER_QUIET

        provider = PromptLog(chat_reply="hi")
        assert await attempt(maker, user_id, now, provider, config) is None
        assert await initiatives(maker) == [] and provider.chat_prompts == []

    run_db(scenario)


def test_no_initiative_without_a_chat_or_without_messages(run_db):
    async def scenario(maker):
        await add_characters(maker, TRIO)
        user_id = await make_user(maker)
        assert await attempt(maker, user_id, hours(7)) is None  # no chat

        async with maker() as s:
            await ChatSessionService(s, ScriptedProvider()).open_character_chat(user_id, "amy")
        assert await attempt(maker, user_id, hours(7)) is None  # chat without messages

    run_db(scenario)


def test_never_two_in_a_row_and_at_most_one_per_gap(run_db):
    async def scenario(maker):
        await add_characters(maker, TRIO)
        user_id = await make_user(maker)
        conv_id = await direct_chat(maker, user_id)

        assert await attempt(maker, user_id, hours(7)) is not None
        assert await attempt(maker, user_id, hours(30)) is None  # unanswered: do not nag

        async with maker() as s:  # the user answers
            s.add(Message(conversation_id=conv_id, sender_type="user", sender_user_id=user_id, content="hi!", message_type="text"))
            await s.commit()

        assert await attempt(maker, user_id, hours(14)) is None  # idle enough, but the gap (24h) is not over
        assert await attempt(maker, user_id, hours(31)) is not None
        assert len(await initiatives(maker)) == 2

    run_db(scenario)


def test_another_users_initiative_does_not_block_this_user(run_db):
    async def scenario(maker):
        await add_characters(maker, TRIO)
        first = await make_user(maker, 1001)
        second = await make_user(maker, 2002)
        await direct_chat(maker, first)
        await direct_chat(maker, second)

        assert await attempt(maker, first, hours(7)) is not None
        assert await attempt(maker, second, hours(7)) is not None  # not blocked by the first one's gap

        first_conv = {conv for conv, *_ in await initiatives(maker)}
        assert len(first_conv) == 2  # one in each user's own chat

    run_db(scenario)


def test_it_only_uses_the_active_chat_and_other_chats_stay_untouched(run_db):
    async def scenario(maker):
        await add_characters(maker, TRIO)
        user_id = await make_user(maker)
        older = await direct_chat(maker, user_id, "amy")
        newer = await direct_chat(maker, user_id, "bob")  # the active one

        result = await attempt(maker, user_id, hours(7))
        assert result.conversation_id == newer and result.speaker_name == "Bob"
        assert [conv for conv, *_ in await initiatives(maker)] == [newer]

        async with maker() as s:
            active = await ChatSessionService(s).get_active(user_id)
            assert active.conversation_id == newer  # still the active chat
            assert older != newer

    run_db(scenario)


def test_a_provider_failure_writes_nothing_and_can_be_retried(run_db):
    async def scenario(maker):
        await add_characters(maker, TRIO)
        user_id = await make_user(maker)
        await direct_chat(maker, user_id)

        assert await attempt(maker, user_id, hours(7), ScriptedProvider(fail=["chat"])) is None
        assert await initiatives(maker) == []
        assert await attempt(maker, user_id, hours(7)) is not None

    run_db(scenario)


# ------------------------------------------------------------------------- group


async def group_chat(maker, user_id, slugs=("amy", "bob")):
    async with maker() as s:
        ctx = await ChatSessionService(s, ScriptedProvider()).create_group(user_id, list(slugs))
        s.add(Message(conversation_id=ctx.conversation_id, sender_type="user", sender_user_id=user_id, content="hello all", message_type="text"))
        await s.commit()
        return ctx.conversation_id


def test_in_a_group_one_member_writes_in_its_own_voice(run_db):
    async def scenario(maker):
        await add_characters(maker, TRIO)
        c = await ids(maker)
        user_id = await make_user(maker)
        conv_id = await group_chat(maker, user_id)

        provider = PromptLog(chat_reply="Bob: anyone up for a movie?")
        result = await attempt(maker, user_id, hours(7), provider, rng=lambda members: members[1])

        assert (result.is_group, result.speaker_name, result.content) == (True, "Bob", "anyone up for a movie?")
        assert await initiatives(maker) == [(conv_id, "character", c["bob"], "anyone up for a movie?")]
        assert "GROUP CHAT" in provider.chat_prompts[-1] and "RIGHT NOW" in provider.chat_prompts[-1]

    run_db(scenario)


def test_a_group_with_an_inactive_member_is_skipped(run_db):
    async def scenario(maker):
        await add_characters(maker, TRIO)
        user_id = await make_user(maker)
        await group_chat(maker, user_id)
        async with maker() as s:
            bob = (await s.execute(select(Character).where(Character.slug == "bob"))).scalar_one()
            bob.is_active = False
            await s.commit()

        assert await attempt(maker, user_id, hours(7)) is None
        assert await initiatives(maker) == []

    run_db(scenario)


def test_the_speaker_uses_only_its_own_memories(run_db):
    async def scenario(maker):
        await add_characters(maker, TRIO)
        c = await ids(maker)
        user_id = await make_user(maker)
        await group_chat(maker, user_id)
        async with maker() as s:
            from app.services.character_memory_service import CharacterMemoryService

            await CharacterMemoryService(s).add_memory(
                user_id=user_id, character_id=c["amy"], category="personal",
                content="CANARY-AMY-ONLY", importance=10, confidence=1.0, memory_key="canary",
            )
            await s.commit()

        provider = PromptLog(chat_reply="hi")
        await attempt(maker, user_id, hours(7), provider, rng=lambda members: members[1])  # Bob speaks
        assert "CANARY-AMY-ONLY" not in provider.chat_prompts[-1]

    run_db(scenario)
