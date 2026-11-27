"""Every image-service attempt is written to the cost ledger."""

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models import ImageGeneration
from tests.image_fakes import BrokenImageProvider, RefusingImageProvider
from tests.telegram_harness import callback_update, message_update
from tests.test_image_flow import started, yes
from tests.test_art_and_group_photos import ask_reply


async def ledger(maker):
    async with maker() as s:
        rows = (await s.execute(select(ImageGeneration).order_by(ImageGeneration.created_at))).scalars().all()
    return [(r.kind, r.source, r.status, r.provider, r.cost) for r in rows]


def test_a_made_picture_is_recorded_as_a_provider_call(run_db, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "XAVIRA_COST_PER_IMAGE", 2.0)

    async def scenario(maker):
        bot, _ = await started(maker, tmp_path)
        await bot.send(message_update("/photo"))
        await yes(bot)
        assert await ledger(maker) == [("photo", "provider", "ok", "unknown", 2.0)]

    run_db(scenario)


def test_cost_is_empty_when_the_unit_cost_is_unknown(run_db, tmp_path):
    async def scenario(maker):
        bot, _ = await started(maker, tmp_path)
        await bot.send(message_update("/photo"))
        await yes(bot)
        assert (await ledger(maker))[0][4] is None

    run_db(scenario)


@pytest.mark.parametrize("provider,status", [(RefusingImageProvider(), "refused"), (BrokenImageProvider(), "failed")])
def test_refused_and_failed_attempts_are_recorded_too(run_db, tmp_path, provider, status):
    async def scenario(maker):
        bot, _ = await started(maker, tmp_path, image_provider=provider)
        await bot.send(message_update("/art"))
        await bot.send(ask_reply("a cat"))
        await yes(bot)
        assert (await ledger(maker))[-1][:3] == ("art", "provider", status)

    run_db(scenario)


def test_a_cache_hit_is_recorded_without_cost(run_db, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "XAVIRA_COST_PER_IMAGE", 2.0)

    async def scenario(maker):
        bot, feat = await started(maker, tmp_path)
        object.__setattr__(feat, "cache_min_variants", 1)
        await bot.send(message_update("/photo"))
        await yes(bot)  # the first user makes the picture
        await bot.send(callback_update("open:amy", user_id=2002, first="Bo"))
        await bot.send(message_update("/photo", user_id=2002, first="Bo"))
        await bot.send(callback_update("imgy", message_id=500, user_id=2002, first="Bo"))
        rows = await ledger(maker)
        assert [(r[1], r[4]) for r in rows] == [("provider", 2.0), ("cache", None)]
        assert len(feat.provider.calls) == 1

    run_db(scenario)
