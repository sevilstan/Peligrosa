"""Credits in the Telegram flow: trial, empty balance, refunds, groups, admin."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.models import Conversation, CreditTransaction, Message, User
from app.services.credit_service import CreditConfig, CreditService
from app.telegram.texts import t
from tests.telegram_harness import Harness, add_characters, callback_update, message_update
from tests.test_conversation_engine import ScriptedProvider

PEOPLE = [("Amy", "amy", 0, True), ("Bob", "bob", 1, True), ("Cy", "cy", 2, True)]


@pytest.fixture
def credits_on(monkeypatch):
    monkeypatch.setattr(settings, "CREDITS_ENABLED", True)
    monkeypatch.setattr(settings, "TRIAL_CREDITS", 2)
    monkeypatch.setattr(settings, "GROUP_CREATE_COST", 50)


async def user_row(maker, telegram_id=1001):
    async with maker() as s:
        return (await s.execute(select(User).where(User.telegram_id == telegram_id))).scalar_one()


async def credits_of(maker, telegram_id=1001):
    return (await user_row(maker, telegram_id)).credits


async def count(maker, model):
    async with maker() as s:
        return (await s.execute(select(func.count()).select_from(model))).scalar_one()


async def started(maker, tmp_path, provider=None):
    await add_characters(maker, PEOPLE)
    bot = Harness(maker, tmp_path, provider)
    await bot.send(callback_update("open:amy"))
    return bot


def test_credits_off_means_no_limits(run_db, tmp_path):
    async def scenario(maker):
        bot = await started(maker, tmp_path)
        for i in range(15):
            await bot.send(message_update(f"m{i}"))
        assert t("en", "credits_empty") not in bot.texts()
        assert await count(maker, Message) == 30

    run_db(scenario)


def test_trial_runs_out_and_the_ai_is_not_called(run_db, tmp_path, credits_on):
    async def scenario(maker):
        provider = ScriptedProvider(chat_reply="hi")
        bot = await started(maker, tmp_path, provider)

        for i in range(3):
            await bot.send(message_update(f"m{i}"))

        assert bot.texts()[-1] == t("en", "credits_empty", cost=1, credits=0)
        assert await credits_of(maker) == 0
        assert await count(maker, Message) == 4  # 2 exchanges; the third was never saved

    run_db(scenario)


def test_failed_reply_gives_the_credit_back(run_db, tmp_path, credits_on):
    async def scenario(maker):
        bot = await started(maker, tmp_path, ScriptedProvider(fail={"chat"}))
        await bot.send(message_update("hello"))
        assert bot.texts()[-1] == t("en", "ai_error")
        assert await credits_of(maker) == 2  # trial granted, nothing spent

    run_db(scenario)


def test_group_creation_needs_credits_or_a_subscription(run_db, tmp_path, credits_on):
    async def scenario(maker):
        await add_characters(maker, PEOPLE)
        bot = Harness(maker, tmp_path)
        await bot.send(message_update("/newgroup"))
        await bot.send(callback_update("gsel:0:amy"))
        await bot.send(callback_update("gsel:0:bob"))

        await bot.send(callback_update("gdone"))
        alerts = [d for n, d in bot.session.calls if n == "AnswerCallbackQuery" and d.get("show_alert")]
        assert alerts[-1]["text"] == t("en", "group_needs_credits", cost=50, credits=2)
        assert await count(maker, Conversation) == 0
        assert await credits_of(maker) == 2

        # With 50 more credits it works and costs 50.
        async with maker() as s:
            await CreditService(s, CreditConfig(enabled=True)).grant((await user_row(maker)).id, 50)
        await bot.send(callback_update("gdone"))
        assert await count(maker, Conversation) == 1
        assert await credits_of(maker) == 2

    run_db(scenario)


def test_a_subscriber_creates_groups_for_free(run_db, tmp_path, credits_on):
    async def scenario(maker):
        await add_characters(maker, PEOPLE)
        bot = Harness(maker, tmp_path)
        await bot.send(message_update("/credits"))  # creates the user
        async with maker() as s:
            await CreditService(s, CreditConfig(enabled=True)).set_subscription(
                (await user_row(maker)).id, datetime.now(timezone.utc) + timedelta(days=5)
            )

        await bot.send(message_update("/newgroup"))
        await bot.send(callback_update("gsel:0:amy"))
        await bot.send(callback_update("gsel:0:bob"))
        await bot.send(callback_update("gdone"))

        assert await count(maker, Conversation) == 1
        assert await credits_of(maker) == 2  # only the trial; nothing spent

    run_db(scenario)


def test_an_invalid_group_does_not_cost_credits(run_db, tmp_path, credits_on):
    async def scenario(maker):
        await add_characters(maker, PEOPLE)
        bot = Harness(maker, tmp_path)
        await bot.send(message_update("/credits"))  # grants the trial now
        await bot.send(message_update("/newgroup"))
        await bot.send(callback_update("gsel:0:amy"))  # only one selected
        async with maker() as s:
            await CreditService(s, CreditConfig(enabled=True)).grant((await user_row(maker)).id, 60)
        before = await credits_of(maker)

        await bot.send(callback_update("gdone"))
        assert await credits_of(maker) == before

    run_db(scenario)


def test_a_group_message_costs_two(run_db, tmp_path, credits_on, monkeypatch):
    async def scenario(maker):
        await add_characters(maker, PEOPLE)
        bot = Harness(maker, tmp_path, ScriptedProvider(chat_reply="hey"))
        await bot.send(message_update("/credits"))
        async with maker() as s:
            await CreditService(s, CreditConfig(enabled=True)).grant((await user_row(maker)).id, 50)
        await bot.send(message_update("/newgroup"))
        await bot.send(callback_update("gsel:0:amy"))
        await bot.send(callback_update("gsel:0:bob"))
        await bot.send(callback_update("gdone"))  # costs 50 -> 2 left (trial)
        assert await credits_of(maker) == 2

        await bot.send(message_update("hello all"))
        assert await credits_of(maker) == 0

    run_db(scenario)


def test_daily_cap_is_explained(run_db, tmp_path, credits_on, monkeypatch):
    monkeypatch.setattr(settings, "SUB_DAILY_MESSAGE_CAP", 1)

    async def scenario(maker):
        bot = await started(maker, tmp_path)
        async with maker() as s:
            await CreditService(s, CreditConfig(enabled=True)).set_subscription(
                (await user_row(maker)).id, datetime.now(timezone.utc) + timedelta(days=5)
            )
        await bot.send(message_update("one"))
        await bot.send(message_update("two"))
        assert bot.texts()[-1] == t("en", "daily_cap")

    run_db(scenario)


def test_credits_command_shows_the_balance(run_db, tmp_path, credits_on):
    async def scenario(maker):
        await add_characters(maker, PEOPLE)
        bot = Harness(maker, tmp_path)
        await bot.send(message_update("/credits"))
        assert bot.texts()[-1] == t(
            "en", "credits_balance", credits=2, message=1, group_message=2, group_create=50
        )

    run_db(scenario)


def test_credits_command_when_off(run_db, tmp_path):
    async def scenario(maker):
        bot = Harness(maker, tmp_path)
        await bot.send(message_update("/credits"))
        assert bot.texts()[-1] == t("en", "credits_off")

    run_db(scenario)


def test_only_an_operator_can_grant(run_db, tmp_path, credits_on, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_TELEGRAM_IDS", "9001, junk")

    async def scenario(maker):
        await add_characters(maker, PEOPLE)
        bot = Harness(maker, tmp_path)
        await bot.send(message_update("/credits", user_id=2002))  # target user exists
        await bot.send(message_update("/credits", user_id=9001, first="Op"))

        # A normal user gets the unknown-command answer and nothing changes.
        await bot.send(message_update("/grant 2002 100", user_id=2002))
        assert bot.texts()[-1] == t("en", "unknown_command")
        assert await credits_of(maker, 2002) == 2

        await bot.send(message_update("/grant 2002 100", user_id=9001))
        assert bot.texts()[-1] == "Granted 100. New balance: 102."
        assert await credits_of(maker, 2002) == 102

        for bad in ("/grant", "/grant 2002", "/grant 2002 -5", "/grant x y", "/grant 2002 0"):
            await bot.send(message_update(bad, user_id=9001))
            assert bot.texts()[-1] == "Usage: /grant <telegram_id> <credits>", bad

        await bot.send(message_update("/grant 777 5", user_id=9001))
        assert bot.texts()[-1] == "No user with that Telegram id."

    run_db(scenario)


def test_operators_are_never_charged_but_everyone_else_is(run_db, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "CREDITS_ENABLED", True)
    monkeypatch.setattr(settings, "TRIAL_CREDITS", 0)  # nobody has any credits
    monkeypatch.setattr(settings, "ADMIN_TELEGRAM_IDS", "1001")

    async def scenario(maker):
        await add_characters(maker, PEOPLE)
        bot = Harness(maker, tmp_path)

        # The operator talks freely, with no credits and no records.
        await bot.send(callback_update("open:amy", user_id=1001))
        await bot.send(message_update("hello", user_id=1001))
        assert t("en", "credits_empty", cost=1, credits=0) not in bot.texts()
        assert any(x.startswith("<b>Amy:</b>") for x in bot.texts())  # she answered
        async with maker() as s:
            assert (await s.execute(select(func.count()).select_from(CreditTransaction))).scalar_one() == 0

        # Anyone else is stopped as usual.
        await bot.send(callback_update("open:amy", user_id=2002, first="Bo"))
        await bot.send(message_update("hello", user_id=2002, first="Bo"))
        assert bot.texts()[-1] == t("en", "credits_empty", cost=1, credits=0)

    run_db(scenario)
