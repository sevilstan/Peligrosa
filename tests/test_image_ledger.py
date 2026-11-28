"""The image ledger: one row per attempt, generation and delivery kept apart."""

import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.models import CreditTransaction, ImageCacheEntry, ImageGeneration
from app.services.image_service import ImageService
from app.services.stats_service import StatsService
from tests.image_fakes import BrokenImageProvider, RefusingImageProvider, SceneProvider
from tests.telegram_harness import callback_update, message_update
from tests.test_art_and_group_photos import ask_reply, credits_on  # noqa: F401
from tests.test_image_flow import started, yes

FAIL = "Bad Request: wrong file identifier"


async def ledger(maker):
    """(kind, source, generation, delivery, provider, Xavira credits) per row."""
    async with maker() as s:
        rows = (await s.execute(select(ImageGeneration).order_by(ImageGeneration.created_at))).scalars().all()
    return [(r.kind, r.source, r.status, r.delivery, r.provider, r.provider_credits) for r in rows]


async def refunds(maker):
    async with maker() as s:
        return (
            await s.execute(select(func.count()).select_from(CreditTransaction).where(CreditTransaction.reason == "refund"))
        ).scalar_one()


def test_a_delivered_picture_is_one_row_generated_and_delivered(run_db, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "XAVIRA_CREDITS_PER_IMAGE", 2.0)

    async def scenario(maker):
        bot, _ = await started(maker, tmp_path)
        await bot.send(message_update("/photo"))
        await yes(bot)
        assert await ledger(maker) == [("photo", "provider", "ok", "delivered", "unknown", 2.0)]

    run_db(scenario)


def test_credits_are_empty_when_the_unit_is_unknown(run_db, tmp_path):
    async def scenario(maker):
        bot, _ = await started(maker, tmp_path)
        await bot.send(message_update("/photo"))
        await yes(bot)
        assert (await ledger(maker))[0][5] is None

    run_db(scenario)


@pytest.mark.parametrize("provider,status", [(RefusingImageProvider(), "refused"), (BrokenImageProvider(), "failed")])
def test_refused_and_failed_generations_have_nothing_to_deliver(run_db, tmp_path, credits_on, monkeypatch, provider, status):
    monkeypatch.setattr(settings, "XAVIRA_CREDITS_PER_IMAGE", 2.0)

    async def scenario(maker):
        bot, _ = await started(maker, tmp_path, image_provider=provider)
        await bot.send(message_update("/art"))
        await bot.send(ask_reply("a cat"))
        await yes(bot)
        # nothing was made: no delivery, and no Xavira credits are claimed
        assert (await ledger(maker))[-1] == ("art", "provider", status, None, "unknown", None)
        assert await refunds(maker) == 1

    run_db(scenario)


def test_a_telegram_failure_keeps_the_provider_credits_and_adds_no_row(run_db, tmp_path, credits_on, monkeypatch):
    monkeypatch.setattr(settings, "XAVIRA_CREDITS_PER_IMAGE", 2.0)

    async def scenario(maker):
        bot, _ = await started(maker, tmp_path)
        bot.session.photo_error = FAIL
        await bot.send(message_update("/photo"))
        await yes(bot)
        # Generation succeeded and used Xavira credits; only delivery failed. One row, one refund.
        assert await ledger(maker) == [("photo", "provider", "ok", "failed", "unknown", 2.0)]
        assert await refunds(maker) == 1

    run_db(scenario)


def test_a_cache_reuse_counts_only_after_delivery(run_db, tmp_path, monkeypatch):
    async def scenario(maker):
        bot, feat = await started(maker, tmp_path)
        object.__setattr__(feat, "cache_min_variants", 1)
        await bot.send(message_update("/photo"))
        await yes(bot)  # user 1: a real call, delivered

        await bot.send(callback_update("open:amy", user_id=2002, first="Bo"))
        bot.session.photo_error = FAIL  # user 2002: the cached picture is not delivered
        await bot.send(message_update("/photo", user_id=2002, first="Bo"))
        await bot.send(callback_update("imgy", message_id=500, user_id=2002, first="Bo"))
        assert (await ledger(maker))[-1][1:4] == ("cache", "ok", "failed")
        async with maker() as s:
            stats = await StatsService(s).collect()
            assert stats.cache_hits == 0
            assert (await s.execute(select(ImageCacheEntry.use_count))).scalar_one() in (0, None)

        bot.session.photo_error = None  # ...and again, delivered this time
        await bot.send(message_update("/photo", user_id=2002, first="Bo"))
        await bot.send(callback_update("imgy", message_id=500, user_id=2002, first="Bo"))
        rows = await ledger(maker)
        assert [r[1:4] for r in rows] == [("provider", "ok", "delivered"), ("cache", "ok", "failed"), ("cache", "ok", "delivered")]
        async with maker() as s:
            assert (await StatsService(s).collect()).cache_hits == 1
            assert (await s.execute(select(ImageCacheEntry.use_count))).scalar_one() == 1

    run_db(scenario)


def test_the_delivery_status_is_set_once_and_never_duplicated(run_db, tmp_path):
    async def scenario(maker):
        from tests.test_image_service import add_messages, feature, seed_conversation

        user_id, character_id, conv_id = await seed_conversation(maker)
        await add_messages(maker, conv_id, user_id, character_id, 4)
        feat = feature(tmp_path)
        async with maker() as s:
            service = ImageService(s, feat, SceneProvider())
            photo = await service.generate(conv_id, user_id, "send a pic")
            assert (await ledger(maker))[0][3] == "pending"
            await service.confirm_delivery(photo)
            await service.mark_delivery_failed(photo)  # too late: it was delivered
            await service.confirm_delivery(photo)  # a second confirm changes nothing
        rows = await ledger(maker)
        assert len(rows) == 1 and rows[0][3] == "delivered"
        async with maker() as s:  # ...and the picture joined the chat exactly once
            from app.models import Message

            assert (await s.execute(select(func.count()).select_from(Message).where(Message.message_type == "image"))).scalar_one() == 1

    run_db(scenario)
