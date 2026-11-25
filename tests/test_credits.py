"""Credits: trial, spending, refunds, subscriptions and concurrency."""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models import CreditTransaction, User
from app.services.credit_service import (
    CreditConfig,
    CreditService,
    DailyCapReached,
    InsufficientCredits,
)
from app.services.telegram_user_service import TelegramUserService

ON = CreditConfig(enabled=True, trial=3, subscriber_daily_cap=2)
NOW = datetime(2026, 11, 25, 12, 0, tzinfo=timezone.utc)


async def make_user(maker, telegram_id=1):
    async with maker() as s:
        return (await TelegramUserService(s).get_or_create(telegram_id, "Ada")).id


def service(s, config=ON, now=NOW):
    return CreditService(s, config, clock=lambda: now)


async def history(maker, user_id):
    async with maker() as s:
        rows = (
            await s.execute(
                select(CreditTransaction)
                .where(CreditTransaction.user_id == user_id)
                .order_by(CreditTransaction.created_at, CreditTransaction.balance_after.desc())
            )
        ).scalars().all()
        return [(r.reason, r.amount, r.balance_after) for r in rows]


def test_disabled_means_no_limits_and_no_records(run_db):
    async def scenario(maker):
        uid = await make_user(maker)
        async with maker() as s:
            svc = CreditService(s, CreditConfig(enabled=False))
            for _ in range(50):
                receipt = await svc.charge(uid, 1, "message")
                assert receipt.amount == 0
        assert await history(maker, uid) == []

    run_db(scenario)


def test_trial_is_granted_once_then_spent_until_empty(run_db):
    async def scenario(maker):
        uid = await make_user(maker)
        async with maker() as s:
            svc = service(s)
            for _ in range(3):
                assert (await svc.charge(uid, 1, "message")).amount == 1
            with pytest.raises(InsufficientCredits) as info:
                await svc.charge(uid, 1, "message")
            assert (info.value.needed, info.value.available) == (1, 0)
            assert (await svc.status(uid)).credits == 0

        # A new session, same user: the trial is not granted again.
        async with maker() as s:
            with pytest.raises(InsufficientCredits):
                await service(s).charge(uid, 1, "message")

        assert await history(maker, uid) == [
            ("trial", 3, 3), ("message", -1, 2), ("message", -1, 1), ("message", -1, 0),
        ]

    run_db(scenario)


def test_a_cost_above_the_balance_changes_nothing(run_db):
    async def scenario(maker):
        uid = await make_user(maker)
        async with maker() as s:
            with pytest.raises(InsufficientCredits):
                await service(s).charge(uid, 50, "group_create")
            assert (await service(s).status(uid)).credits == 3  # trial kept, nothing spent

    run_db(scenario)


def test_refund_gives_back_exactly_what_was_spent(run_db):
    async def scenario(maker):
        uid = await make_user(maker)
        async with maker() as s:
            svc = service(s)
            receipt = await svc.charge(uid, 2, "group_message")
            assert (await svc.status(uid)).credits == 1
            await svc.refund(receipt)
            assert (await svc.status(uid)).credits == 3
            await svc.refund((await svc.charge(uid, 0, "message")))  # free: no-op
            assert (await svc.status(uid)).credits == 3

    run_db(scenario)


def test_grants_add_credits_and_must_be_positive(run_db):
    async def scenario(maker):
        uid = await make_user(maker)
        async with maker() as s:
            svc = service(s)
            await svc.charge(uid, 1, "message")  # trial first
            assert await svc.grant(uid, 50) == 52
            for bad in (0, -5):
                with pytest.raises(ValueError):
                    await svc.grant(uid, bad)

    run_db(scenario)


def test_subscriber_spends_nothing_but_has_a_daily_cap(run_db):
    async def scenario(maker):
        uid = await make_user(maker)
        async with maker() as s:
            svc = service(s)
            await svc.set_subscription(uid, NOW + timedelta(days=30))
            assert (await svc.status(uid)).subscribed is True

            for _ in range(2):
                assert (await svc.charge(uid, 1, "message")).amount == 0
            with pytest.raises(DailyCapReached):
                await svc.charge(uid, 1, "group_message")

            # Group creation is included and does not count as a message.
            assert (await svc.charge(uid, 50, "group_create")).amount == 0
            # Things the subscription does not include still cost credits.
            assert (await svc.charge(uid, 2, "image", included_in_subscription=False)).amount == 2
            assert (await svc.status(uid)).credits == 1

            # Tomorrow the allowance is back.
            tomorrow = service(s, now=NOW + timedelta(days=1))
            assert (await tomorrow.charge(uid, 1, "message")).amount == 0

    run_db(scenario)


def test_an_expired_subscription_means_credits_again(run_db):
    async def scenario(maker):
        uid = await make_user(maker)
        async with maker() as s:
            svc = service(s)
            await svc.set_subscription(uid, NOW - timedelta(seconds=1))
            assert (await svc.status(uid)).subscribed is False
            assert (await svc.charge(uid, 1, "message")).amount == 1

    run_db(scenario)


def test_simultaneous_charges_never_overspend(run_db):
    async def scenario(maker):
        uid = await make_user(maker)

        async def attempt():
            async with maker() as s:
                try:
                    await service(s).charge(uid, 1, "message")
                    return True
                except InsufficientCredits:
                    return False

        results = await asyncio.gather(*(attempt() for _ in range(10)))
        assert results.count(True) == 3  # exactly the trial
        async with maker() as s:
            assert (await service(s).status(uid)).credits == 0

    run_db(scenario)


def test_credits_are_per_user(run_db):
    async def scenario(maker):
        a, b = await make_user(maker, 1), await make_user(maker, 2)
        async with maker() as s:
            svc = service(s)
            for _ in range(3):
                await svc.charge(a, 1, "message")
            assert (await svc.charge(b, 1, "message")).amount == 1
            assert (await svc.status(b)).credits == 2

    run_db(scenario)


def test_unknown_user_and_negative_cost_are_errors(run_db):
    import uuid

    async def scenario(maker):
        uid = await make_user(maker)
        async with maker() as s:
            with pytest.raises(ValueError):
                await service(s).charge(uuid.uuid4(), 1, "message")
            with pytest.raises(ValueError):
                await service(s).charge(uid, -1, "message")

    run_db(scenario)
