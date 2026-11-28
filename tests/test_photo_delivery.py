"""A picture joins the chat (and the gallery) only after Telegram delivered it."""

import logging

import pytest
from sqlalchemy import func, select

from app.models import CreditTransaction, ImageCacheEntry, Message, User
from app.services.image_service import ImageService
from app.services.picture_gallery_service import PictureGalleryService
from tests.telegram_harness import callback_update, message_update
from tests.test_art_and_group_photos import ask_reply, credits_on, group_chat  # noqa: F401
from tests.test_image_flow import image_messages, started, user_credits, yes

FAIL = "Bad Request: wrong file identifier"


async def refunds(maker):
    async with maker() as s:
        return (
            await s.execute(select(func.count()).select_from(CreditTransaction).where(CreditTransaction.reason == "refund"))
        ).scalar_one()


async def gallery_size(maker, telegram_id=1001):
    async with maker() as s:
        user = (await s.execute(select(User).where(User.telegram_id == telegram_id))).scalar_one()
        return len(await PictureGalleryService(s).list_for_user(user.id))


async def start_photo(bot):
    await bot.send(message_update("/photo"))


async def start_art(bot):
    await bot.send(message_update("/art"))
    await bot.send(ask_reply("a knight on a dragon"))


@pytest.mark.parametrize("begin", [start_photo, start_art])
def test_a_failed_delivery_leaves_no_picture_and_refunds_once(run_db, tmp_path, credits_on, begin):
    async def scenario(maker):
        bot, feat = await started(maker, tmp_path)
        bot.session.photo_error = FAIL
        await begin(bot)
        await yes(bot)

        assert await image_messages(maker) == 0
        assert await gallery_size(maker) == 0
        assert await refunds(maker) == 1
        assert await user_credits(maker) == 20  # trial credits, nothing lost

    run_db(scenario)


@pytest.mark.parametrize("begin", [start_photo, start_art])
def test_a_delivered_picture_is_saved_once_and_never_refunded(run_db, tmp_path, credits_on, begin):
    async def scenario(maker):
        bot, _ = await started(maker, tmp_path)
        await begin(bot)
        await yes(bot)

        assert await image_messages(maker) == 1
        assert await gallery_size(maker) == 1
        assert await refunds(maker) == 0

    run_db(scenario)


def test_a_failed_group_delivery_leaves_nothing_either(run_db, tmp_path, credits_on):
    async def scenario(maker):
        bot, _ = await started(maker, tmp_path)
        await group_chat(bot)
        bot.session.photo_error = FAIL
        await bot.send(message_update("/photo"))
        await bot.send(callback_update("imgp:bob"))
        await yes(bot)
        assert await image_messages(maker) == 0 and await refunds(maker) == 1

    run_db(scenario)


def test_a_failed_delivery_does_not_use_up_a_cached_picture(run_db, tmp_path):
    async def scenario(maker):
        bot, feat = await started(maker, tmp_path)
        object.__setattr__(feat, "cache_min_variants", 1)
        await start_photo(bot)
        await yes(bot)  # user 1 makes the picture

        await bot.send(callback_update("open:amy", user_id=2002, first="Bo"))
        bot.session.photo_error = FAIL
        await bot.send(message_update("/photo", user_id=2002, first="Bo"))
        await bot.send(callback_update("imgy", message_id=500, user_id=2002, first="Bo"))
        async with maker() as s:
            assert (await s.execute(select(ImageCacheEntry.use_count))).scalar_one() in (0, None)
        assert await gallery_size(maker, 2002) == 0

        bot.session.photo_error = None  # the same picture is still fresh for them
        await bot.send(message_update("/photo", user_id=2002, first="Bo"))
        await bot.send(callback_update("imgy", message_id=500, user_id=2002, first="Bo"))
        async with maker() as s:
            assert (await s.execute(select(ImageCacheEntry.use_count))).scalar_one() == 1
        assert await gallery_size(maker, 2002) == 1
        assert len(feat.provider.calls) == 1  # never asked Xavira a second time

    run_db(scenario)


def test_if_saving_fails_after_delivery_the_user_keeps_the_photo_without_a_refund(
    run_db, tmp_path, credits_on, monkeypatch, caplog
):
    async def scenario(maker):
        async def boom(self, photo):
            raise RuntimeError("database down")

        monkeypatch.setattr(ImageService, "confirm_delivery", boom)
        bot, _ = await started(maker, tmp_path)
        await start_photo(bot)
        await yes(bot)

        assert len(bot.session.named("SendPhoto")) == 1  # delivered
        assert await refunds(maker) == 0 and await user_credits(maker) == 15
        assert "could not be saved to the chat" in caplog.text

    run_db(scenario)
