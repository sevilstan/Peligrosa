"""Selling credits and subscriptions for Telegram Stars."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.models import CreditTransaction, StarPayment, User
from app.services.payment_service import Product, build_catalog, parse_packs
from app.telegram.texts import t
from tests.telegram_harness import (
    Harness,
    add_characters,
    callback_update,
    message_update,
    pre_checkout_update,
    successful_payment_update,
)


@pytest.fixture
def shop(monkeypatch):
    monkeypatch.setattr(settings, "CREDITS_ENABLED", True)
    monkeypatch.setattr(settings, "TRIAL_CREDITS", 2)
    monkeypatch.setattr(settings, "CREDIT_PACKS", "100:50,300:125")
    monkeypatch.setattr(settings, "SUB_PRICE_STARS", 400)
    monkeypatch.setattr(settings, "SUB_DAYS", 30)
    monkeypatch.setattr(settings, "SUB_BONUS_CREDITS", 0)
    monkeypatch.setattr(settings, "ADMIN_TELEGRAM_IDS", "9001")
    monkeypatch.setattr(settings, "SUPPORT_CONTACT", "@helpdesk")


async def user_row(maker, telegram_id=1001):
    async with maker() as s:
        return (await s.execute(select(User).where(User.telegram_id == telegram_id))).scalar_one()


async def payments(maker):
    async with maker() as s:
        return (await s.execute(select(StarPayment))).scalars().all()


async def beginner(maker, tmp_path):
    bot = Harness(maker, tmp_path)
    await bot.send(message_update("/credits"))  # creates the user, grants the trial (2)
    return bot


# ------------------------------------------------------------------ catalog


def test_packs_are_parsed_and_typos_cannot_break_the_shop():
    assert parse_packs("100:50, 300:125") == [
        Product("pack100", 50, credits=100),
        Product("pack300", 125, credits=300),
    ]
    assert parse_packs("") == []
    # bad entries are skipped, good ones stay; duplicates keep the first
    assert [p.key for p in parse_packs("x, 100:, 0:5, 5:0, 10:10:10, 100:50, 100:99")] == ["pack100"]
    assert parse_packs("100:50,100:99")[0].stars == 50


def test_catalog_adds_the_subscription_from_settings(monkeypatch):
    monkeypatch.setattr(settings, "CREDIT_PACKS", "100:50")
    monkeypatch.setattr(settings, "SUB_PRICE_STARS", 400)
    monkeypatch.setattr(settings, "SUB_DAYS", 30)
    monkeypatch.setattr(settings, "SUB_BONUS_CREDITS", 20)
    catalog = build_catalog(settings)
    assert catalog[-1] == Product("sub", 400, credits=20, days=30)

    monkeypatch.setattr(settings, "SUB_PRICE_STARS", 0)
    assert [p.key for p in build_catalog(settings)] == ["pack100"]


# ----------------------------------------------------------------- the shop


def test_the_shop_lists_products_and_sends_invoices(run_db, tmp_path, shop):
    async def scenario(maker):
        bot = await beginner(maker, tmp_path)
        await bot.send(message_update("/buy"))
        assert bot.texts()[-1] == t("en", "buy_menu")
        assert bot.callback_data() == ["buyitem:pack100", "buyitem:pack300", "buyitem:sub"]

        await bot.send(callback_update("buyitem:pack300"))
        invoice = bot.session.named("SendInvoice")[-1]
        assert invoice["currency"] == "XTR" and invoice["payload"] == "buy:pack300"
        assert invoice["prices"][0]["amount"] == 125
        assert invoice["provider_token"] == ""

        await bot.send(callback_update("buyitem:sub"))
        invoice = bot.session.named("SendInvoice")[-1]
        assert invoice["prices"][0]["amount"] == 400 and invoice["payload"] == "buy:sub"
        assert "100 messages a day" in invoice["description"]

    run_db(scenario)


def test_unknown_products_and_a_closed_shop(run_db, tmp_path, shop, monkeypatch):
    async def scenario(maker):
        bot = await beginner(maker, tmp_path)
        await bot.send(callback_update("buyitem:nonsense"))
        assert bot.session.named("SendInvoice") == []

        monkeypatch.setattr(settings, "CREDITS_ENABLED", False)
        await bot.send(message_update("/buy"))
        assert bot.texts()[-1] == t("en", "buy_unavailable")

    run_db(scenario)


def test_empty_credits_offer_the_shop(run_db, tmp_path, shop):
    async def scenario(maker):
        await add_characters(maker, [("Amy", "amy", 0, True)])
        bot = Harness(maker, tmp_path)
        await bot.send(callback_update("open:amy"))
        for i in range(3):
            await bot.send(message_update(f"m{i}"))
        assert bot.texts()[-1] == t("en", "credits_empty", cost=1, credits=0)
        assert bot.callback_data() == ["buyopen"]

        await bot.send(callback_update("buyopen"))
        assert bot.texts()[-1] == t("en", "buy_menu")

    run_db(scenario)


# ----------------------------------------------------------------- checkout


def test_precheckout_accepts_only_real_products_at_todays_price(run_db, tmp_path, shop):
    async def scenario(maker):
        bot = await beginner(maker, tmp_path)

        async def answer(payload, total, currency="XTR"):
            await bot.send(pre_checkout_update(payload, total, currency=currency))
            return bot.session.named("AnswerPreCheckoutQuery")[-1]

        assert (await answer("buy:pack100", 50))["ok"] is True
        assert (await answer("buy:sub", 400))["ok"] is True
        for bad in (("buy:pack100", 49), ("buy:pack100", 51), ("buy:missing", 50), ("hack", 50),
                    ("buy:pack100", 50, "USD")):
            result = await answer(*bad)
            assert result["ok"] is False, bad
            assert result["error_message"] == t("en", "precheckout_rejected")

    run_db(scenario)


# ----------------------------------------------------------------- delivery


def test_paying_for_a_pack_delivers_credits_once(run_db, tmp_path, shop):
    async def scenario(maker):
        bot = await beginner(maker, tmp_path)
        pay = successful_payment_update("buy:pack100", 50, "charge-1")

        await bot.send(pay)
        assert bot.texts()[-1] == t("en", "pay_thanks_pack", credits=102)
        assert (await user_row(maker)).credits == 102

        # Telegram repeats the notification: nothing more happens.
        count = len(bot.texts())
        await bot.send(pay)
        assert (await user_row(maker)).credits == 102
        assert len(bot.texts()) == count
        stored = await payments(maker)
        assert len(stored) == 1 and stored[0].stars == 50 and stored[0].status == "paid"

    run_db(scenario)


def test_a_subscription_extends_from_the_end_date(run_db, tmp_path, shop):
    async def scenario(maker):
        bot = await beginner(maker, tmp_path)
        await bot.send(successful_payment_update("buy:sub", 400, "charge-a"))
        first = (await user_row(maker)).subscription_until
        assert first > datetime.now(timezone.utc) + timedelta(days=29)

        # Buying again before it ends adds 30 more days on top.
        await bot.send(successful_payment_update("buy:sub", 400, "charge-b"))
        second = (await user_row(maker)).subscription_until
        assert second == first + timedelta(days=30)

        # A subscriber is no longer charged per message (up to the daily cap).
        await add_characters(maker, [("Amy", "amy", 0, True)])
        await bot.send(callback_update("open:amy"))
        before = (await user_row(maker)).credits
        await bot.send(message_update("hi"))
        assert (await user_row(maker)).credits == before

    run_db(scenario)


def test_a_payment_for_a_product_no_longer_on_sale_is_kept_for_review(run_db, tmp_path, shop):
    async def scenario(maker):
        bot = await beginner(maker, tmp_path)
        await bot.send(successful_payment_update("buy:pack9999", 70, "charge-x"))
        assert bot.texts()[-1] == t("en", "pay_problem")
        stored = await payments(maker)
        assert len(stored) == 1 and stored[0].status == "needs_review"
        assert (await user_row(maker)).credits == 2  # nothing was guessed

    run_db(scenario)


def test_payment_and_credits_are_saved_together(run_db, tmp_path, shop):
    async def scenario(maker):
        bot = await beginner(maker, tmp_path)
        await bot.send(successful_payment_update("buy:pack300", 125, "charge-2"))
        async with maker() as s:
            rows = (await s.execute(select(CreditTransaction.reason, CreditTransaction.amount))).all()
        assert ("buy_pack300", 300) in rows

    run_db(scenario)


# ------------------------------------------------------------------ refunds


def test_operator_refund_takes_back_what_was_bought(run_db, tmp_path, shop):
    async def scenario(maker):
        bot = await beginner(maker, tmp_path)
        await bot.send(message_update("/credits", user_id=9001, first="Op"))
        await bot.send(successful_payment_update("buy:pack100", 50, "charge-3"))
        await bot.send(successful_payment_update("buy:sub", 400, "charge-4"))

        await bot.send(message_update("/refund charge-3", user_id=9001))
        assert bot.session.named("RefundStarPayment")[-1] == {
            "user_id": 1001, "telegram_payment_charge_id": "charge-3",
        }
        assert (await user_row(maker)).credits == 2  # the 100 are gone again

        await bot.send(message_update("/refund charge-4", user_id=9001))
        assert (await user_row(maker)).subscription_until <= datetime.now(timezone.utc) + timedelta(seconds=5)

        # Doing it twice does nothing.
        calls = len(bot.session.named("RefundStarPayment"))
        await bot.send(message_update("/refund charge-3", user_id=9001))
        assert bot.texts()[-1] == "Already refunded."
        assert len(bot.session.named("RefundStarPayment")) == calls

    run_db(scenario)


def test_refund_changes_nothing_when_telegram_refuses(run_db, tmp_path, shop):
    async def scenario(maker):
        bot = await beginner(maker, tmp_path)
        await bot.send(message_update("/credits", user_id=9001, first="Op"))
        await bot.send(successful_payment_update("buy:pack100", 50, "charge-5"))
        bot.session.refund_error = "CHARGE_ALREADY_REFUNDED"

        await bot.send(message_update("/refund charge-5", user_id=9001))
        assert bot.texts()[-1] == "Telegram refused the refund. Nothing was changed."
        assert (await user_row(maker)).credits == 102
        assert (await payments(maker))[0].status == "paid"

    run_db(scenario)


def test_only_operators_can_refund(run_db, tmp_path, shop):
    async def scenario(maker):
        bot = await beginner(maker, tmp_path)
        await bot.send(successful_payment_update("buy:pack100", 50, "charge-6"))
        await bot.send(message_update("/refund charge-6"))
        assert bot.texts()[-1] == t("en", "unknown_command")
        assert bot.session.named("RefundStarPayment") == []
        assert (await user_row(maker)).credits == 102

    run_db(scenario)


# ------------------------------------------------------------ terms/support


def test_terms_and_support_commands(run_db, tmp_path, shop, monkeypatch):
    async def scenario(maker):
        bot = Harness(maker, tmp_path)
        await bot.send(message_update("/terms"))
        assert bot.texts()[-1] == t("en", "terms_text")
        await bot.send(message_update("/support"))
        assert bot.texts()[-1] == t("en", "support_text", contact="@helpdesk")
        await bot.send(message_update("/paysupport"))
        assert bot.texts()[-1] == t("en", "paysupport_text", contact="@helpdesk")

        monkeypatch.setattr(settings, "SUPPORT_CONTACT", "")
        await bot.send(message_update("/support"))
        assert bot.texts()[-1] == t("en", "support_missing")

    run_db(scenario)


def test_sub_group_creation_can_be_paid_even_for_subscribers(run_db, tmp_path, shop, monkeypatch):
    monkeypatch.setattr(settings, "SUB_GROUP_CREATE_FREE", False)

    async def scenario(maker):
        await add_characters(maker, [("Amy", "amy", 0, True), ("Bob", "bob", 1, True)])
        bot = await beginner(maker, tmp_path)
        await bot.send(successful_payment_update("buy:sub", 400, "charge-7"))
        await bot.send(message_update("/newgroup"))
        await bot.send(callback_update("gsel:0:amy"))
        await bot.send(callback_update("gsel:0:bob"))
        await bot.send(callback_update("gdone"))
        alerts = [d for n, d in bot.session.calls if n == "AnswerCallbackQuery" and d.get("show_alert")]
        assert alerts and "50 credits" in alerts[-1]["text"]

    run_db(scenario)
