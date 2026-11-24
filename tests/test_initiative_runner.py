"""The background loop and the /proactive command (no real Telegram)."""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.methods import SendMessage
from sqlalchemy import select, update

from app.core.config import settings
from app.models import Message, User
from app.services.initiative_service import INITIATIVE_MESSAGE_TYPE, InitiativeConfig
from app.telegram.bot import build_dispatcher, build_initiative_runner
from app.telegram.chat_utils import UserLocks
from app.telegram.initiative_runner import InitiativeRunner
from app.telegram.texts import t
from tests.telegram_harness import FakeSession, Harness, message_update
from tests.test_character_state import ids  # noqa: F401
from tests.test_conversation_engine import ScriptedProvider
from tests.test_group_messaging import TRIO, PromptLog, add_characters
from tests.test_initiative import NEVER_QUIET, direct_chat, group_chat, initiatives, make_user


async def age_messages(maker, hours=7):
    """Make every existing message look `hours` old."""
    async with maker() as s:
        await s.execute(update(Message).values(created_at=datetime.now(timezone.utc) - timedelta(hours=hours)))
        await s.commit()


def runner_for(maker, provider=None, session=None, locks=None, max_per_check=5):
    session = session or FakeSession()
    bot = Bot(token="123456:TEST", session=session)
    runner = InitiativeRunner(
        bot, maker, provider or PromptLog(chat_reply="Hey, long time!"), locks or UserLocks(),
        NEVER_QUIET, check_seconds=0, max_per_check=max_per_check,
    )
    return runner, session


class BlockedSession(FakeSession):
    def __init__(self, error):
        super().__init__()
        self.error = error

    async def make_request(self, bot, method, timeout=None):
        if isinstance(method, SendMessage):
            raise self.error(method=method, message="Forbidden: bot was blocked by the user")
        return await super().make_request(bot, method, timeout)


# ----------------------------------------------------------------------- runner


def test_a_direct_initiative_is_sent_as_plain_text_to_the_users_chat(run_db):
    async def scenario(maker):
        await add_characters(maker, TRIO)
        user_id = await make_user(maker, 1001)
        await direct_chat(maker, user_id)
        await age_messages(maker)

        runner, session = runner_for(maker, PromptLog(chat_reply="<b>Hey</b>, long time!"))
        assert await runner.run_once() == 1

        [call] = session.named("SendMessage")
        assert (call["chat_id"], call["text"], call.get("parse_mode")) == (1001, "<b>Hey</b>, long time!", None)
        assert len(await initiatives(maker)) == 1
        assert await runner.run_once() == 0  # nothing more until the user answers

    run_db(scenario)


def test_a_group_initiative_opens_with_the_escaped_speaker_name(run_db):
    async def scenario(maker):
        await add_characters(maker, [("Amy <3", "amy", 0, True), ("Bob", "bob", 1, True)])
        user_id = await make_user(maker, 1001)
        await group_chat(maker, user_id)
        await age_messages(maker)

        runner, session = runner_for(maker, PromptLog(chat_reply="a < b"))
        asked = []

        def choose(members):
            asked.append([m.name for m in members])
            return members[0]  # Amy writes

        runner.choose_speaker = choose
        assert await runner.run_once() == 1
        assert asked == [["Amy <3", "Bob"]]  # the runner's chooser was really used

        [call] = session.named("SendMessage")
        assert call["text"] == "<b>Amy &lt;3:</b> a &lt; b" and call["parse_mode"] == "HTML"

    run_db(scenario)


def test_only_opted_in_users_are_considered_and_the_cap_is_respected(run_db):
    async def scenario(maker):
        await add_characters(maker, TRIO)
        for telegram_id, opted in ((1, True), (2, True), (3, True), (4, False)):
            user_id = await make_user(maker, telegram_id, opted_in=opted)
            await direct_chat(maker, user_id)
        await age_messages(maker)

        runner, session = runner_for(maker, max_per_check=2)
        assert await runner.run_once() == 2
        assert len(session.named("SendMessage")) == 2
        assert 4 not in {c["chat_id"] for c in session.named("SendMessage")}

        assert await runner.run_once() == 1  # the third one, next check
        assert {c["chat_id"] for c in session.named("SendMessage")} == {1, 2, 3}

    run_db(scenario)


def test_a_user_in_a_live_conversation_is_skipped(run_db):
    async def scenario(maker):
        await add_characters(maker, TRIO)
        user_id = await make_user(maker, 1001)
        await direct_chat(maker, user_id)
        await age_messages(maker)

        locks = UserLocks()
        runner, session = runner_for(maker, locks=locks)

        async with locks.for_user(1001):  # the user's message is being answered
            assert await runner.run_once() == 0
        assert session.calls == [] and await initiatives(maker) == []

        assert await runner.run_once() == 1

    run_db(scenario)


def test_a_user_who_blocked_the_bot_is_turned_off(run_db):
    async def scenario(maker):
        await add_characters(maker, TRIO)
        user_id = await make_user(maker, 1001)
        await direct_chat(maker, user_id)
        await age_messages(maker)

        runner, _ = runner_for(maker, session=BlockedSession(TelegramForbiddenError))
        assert await runner.run_once() == 0
        async with maker() as s:
            assert (await s.get(User, user_id)).proactive_enabled is False

        runner, session = runner_for(maker)
        assert await runner.run_once() == 0 and session.calls == []  # not tried again

    run_db(scenario)


def test_other_delivery_errors_do_not_turn_the_user_off(run_db):
    async def scenario(maker):
        await add_characters(maker, TRIO)
        user_id = await make_user(maker, 1001)
        await direct_chat(maker, user_id)
        await age_messages(maker)

        runner, _ = runner_for(maker, session=BlockedSession(TelegramBadRequest))
        assert await runner.run_once() == 0
        async with maker() as s:
            assert (await s.get(User, user_id)).proactive_enabled is True

    run_db(scenario)


def test_a_provider_failure_sends_nothing_and_the_loop_survives_errors(run_db):
    async def scenario(maker):
        await add_characters(maker, TRIO)
        user_id = await make_user(maker, 1001)
        await direct_chat(maker, user_id)
        await age_messages(maker)

        runner, session = runner_for(maker, ScriptedProvider(fail=["chat"]))
        assert await runner.run_once() == 0 and session.calls == []

        calls = []

        async def flaky():
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("database hiccup")
            return 0

        runner.run_once = flaky
        task = asyncio.create_task(runner.run_forever())
        for _ in range(50):
            await asyncio.sleep(0.01)
            if len(calls) >= 2:
                break
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert len(calls) >= 2  # it kept going after the first failure

    run_db(scenario)


def test_bot_wiring_uses_the_configured_numbers_and_the_shared_lock(run_db, monkeypatch):
    async def scenario(maker):
        monkeypatch.setattr(settings, "INITIATIVE_CHECK_SECONDS", 123)
        monkeypatch.setattr(settings, "INITIATIVE_MAX_PER_CHECK", 7)
        monkeypatch.setattr(settings, "INITIATIVE_MIN_GAP_HOURS", 11.0)
        locks = UserLocks()
        bot = Bot(token="123456:TEST", session=FakeSession())

        runner = build_initiative_runner(bot, maker, None, locks)
        assert (runner.check_seconds, runner.max_per_check, runner.config.min_gap_hours) == (123, 7, 11.0)
        assert runner.locks is locks

        dispatcher = build_dispatcher(maker, locks=locks)
        from app.telegram.middlewares import ChatOrderMiddleware

        middlewares = list(dispatcher.update.outer_middleware)
        assert any(isinstance(m, ChatOrderMiddleware) and m.locks is locks for m in middlewares)

    run_db(scenario)


# ------------------------------------------------------------------- /proactive


def test_proactive_command_is_unavailable_until_the_operator_enables_it(run_db, tmp_path, monkeypatch):
    async def scenario(maker):
        monkeypatch.setattr(settings, "INITIATIVE_ENABLED", False)
        bot = Harness(maker, tmp_path)
        await bot.send(message_update("/proactive on"))
        assert bot.texts()[-1] == t("en", "proactive_unavailable")
        async with maker() as s:
            assert (await s.execute(select(User.proactive_enabled))).scalar_one() is False

    run_db(scenario)


def test_proactive_command_turns_the_opt_in_on_and_off(run_db, tmp_path, monkeypatch):
    async def scenario(maker):
        monkeypatch.setattr(settings, "INITIATIVE_ENABLED", True)
        bot = Harness(maker, tmp_path)

        async def flag():
            async with maker() as s:
                return (await s.execute(select(User.proactive_enabled))).scalar_one()

        await bot.send(message_update("/proactive"))
        assert bot.texts()[-1] == t("en", "proactive_status_off") and await flag() is False

        await bot.send(message_update("/proactive on"))
        assert bot.texts()[-1] == t("en", "proactive_on") and await flag() is True

        await bot.send(message_update("/proactive"))
        assert bot.texts()[-1] == t("en", "proactive_status_on")

        await bot.send(message_update("/proactive nonsense"))
        assert await flag() is True  # unknown words change nothing

        await bot.send(message_update("/proactive OFF"))
        assert bot.texts()[-1] == t("en", "proactive_off") and await flag() is False

    run_db(scenario)


def test_proactive_command_speaks_turkish(run_db, tmp_path, monkeypatch):
    async def scenario(maker):
        monkeypatch.setattr(settings, "INITIATIVE_ENABLED", True)
        bot = Harness(maker, tmp_path)
        await bot.send(message_update("/proactive aç", lang="tr"))
        assert bot.texts()[-1] == t("tr", "proactive_on")
        await bot.send(message_update("/proactive kapat", lang="tr"))
        assert bot.texts()[-1] == t("tr", "proactive_off")

    run_db(scenario)
