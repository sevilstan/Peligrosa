"""Asking for a picture in Telegram: the button, the offer, yes/no, money."""

import pytest
from sqlalchemy import func, select, update

from app.core.config import settings
from app.models import ImageCacheEntry, Message, User
from app.services.image_service import ImageFeature
from app.services.image_storage import LocalImageStorage
from app.telegram import keyboards
from app.telegram.texts import t
from tests.image_fakes import (
    BrokenImageProvider,
    FakeImageProvider,
    FakeLoader,
    RefusingImageProvider,
    SceneProvider,
    definition,
)
from tests.telegram_harness import Harness, add_characters, callback_update, message_update

PEOPLE = [("Amy", "amy", 0, True), ("Bob", "bob", 1, True)]
OFFER_MESSAGE_ID = 500  # what the fake Telegram numbers every sent message


def feature(tmp_path, provider=None, loader=None):
    return ImageFeature(
        provider=provider or FakeImageProvider(),
        storage=LocalImageStorage(tmp_path / "images"),
        loader=loader or FakeLoader(definition("amy", "Amy"), definition("bob", "Bob", image_id="xav-bob-12345")),
        cache_min_variants=2,
    )


async def started(maker, tmp_path, images=True, image_provider=None, loader=None, chat=None):
    await add_characters(maker, PEOPLE)
    feat = feature(tmp_path, image_provider, loader) if images else None
    bot = Harness(maker, tmp_path, chat or SceneProvider(chat_reply="ok"), images=feat)
    await bot.send(callback_update("open:amy"))
    return bot, feat


def yes(bot):
    return bot.send(callback_update("imgy", message_id=OFFER_MESSAGE_ID))


def no(bot):
    return bot.send(callback_update("imgn", message_id=OFFER_MESSAGE_ID))


async def user_credits(maker):
    async with maker() as s:
        return (await s.execute(select(User.credits).where(User.telegram_id == 1001))).scalar_one()


async def set_credits(maker, amount):
    async with maker() as s:
        await s.execute(update(User).where(User.telegram_id == 1001).values(credits=amount))
        await s.commit()


async def image_messages(maker):
    async with maker() as s:
        return (await s.execute(select(func.count()).select_from(Message).where(Message.message_type == "image"))).scalar_one()


@pytest.fixture
def credits_on(monkeypatch):
    monkeypatch.setattr(settings, "CREDITS_ENABLED", True)
    monkeypatch.setattr(settings, "TRIAL_CREDITS", 10)
    monkeypatch.setattr(settings, "IMAGE_COST", 5)


def test_the_menu_shows_the_photo_button_only_when_pictures_are_on(monkeypatch):
    def labels():
        return [b.text for row in keyboards.main_menu("en").keyboard for b in row]

    monkeypatch.setattr(settings, "IMAGES_ENABLED", False)
    assert t("en", "menu_photo") not in labels()
    monkeypatch.setattr(settings, "IMAGES_ENABLED", True)
    assert t("en", "menu_photo") in labels()


def test_the_command_and_the_button_both_make_an_offer(run_db, tmp_path):
    async def scenario(maker):
        bot, _ = await started(maker, tmp_path)

        await bot.send(message_update("/photo"))
        assert bot.texts()[-1] == t("en", "img_offer_free", name="Amy")
        assert bot.callback_data() == ["imgy", "imgn"]

        await bot.send(message_update(t("en", "menu_photo")))
        assert bot.texts()[-1] == t("en", "img_offer_free", name="Amy")
        assert len([x for x in bot.texts() if x == t("en", "img_offer_free", name="Amy")]) == 2

    run_db(scenario)


def test_the_offer_names_the_price_when_credits_are_on(run_db, tmp_path, credits_on):
    async def scenario(maker):
        bot, _ = await started(maker, tmp_path)
        await bot.send(message_update("/photo"))
        assert bot.texts()[-1] == t("en", "img_offer", name="Amy", cost=5)

    run_db(scenario)


@pytest.mark.parametrize("case", ["off", "no_chat", "undrawable", "group"])
def test_no_offer_when_it_cannot_work(run_db, tmp_path, case):
    async def scenario(maker):
        if case == "no_chat":
            await add_characters(maker, PEOPLE)
            bot = Harness(maker, tmp_path, SceneProvider(), images=feature(tmp_path))
            expected = t("en", "img_no_chat")
        elif case == "off":
            bot, _ = await started(maker, tmp_path, images=False)
            expected = t("en", "img_off")
        elif case == "undrawable":
            bot, _ = await started(maker, tmp_path, loader=FakeLoader())
            expected = t("en", "img_unavailable", name="Amy")
        else:
            bot, _ = await started(maker, tmp_path)
            await bot.send(message_update("/newgroup"))
            await bot.send(callback_update("gsel:0:amy"))
            await bot.send(callback_update("gsel:0:bob"))
            await bot.send(callback_update("gdone"))
            expected = t("en", "img_group")

        await bot.send(message_update("/photo"))

        assert bot.texts()[-1] == expected
        assert not bot.session.named("SendPhoto")

    run_db(scenario)


def test_yes_pays_makes_and_sends_the_picture(run_db, tmp_path, credits_on):
    async def scenario(maker):
        bot, feat = await started(maker, tmp_path)
        await bot.send(message_update("/photo"))

        await yes(bot)

        assert len(feat.provider.calls) == 1
        assert len(bot.session.named("SendPhoto")) == 1
        assert bot.session.named("DeleteMessage")  # the offer is tidied away
        assert await user_credits(maker) == 5  # 10 trial - 5 for the picture
        assert await image_messages(maker) == 1

    run_db(scenario)


def test_no_costs_nothing_and_calls_nobody(run_db, tmp_path, credits_on):
    async def scenario(maker):
        bot, feat = await started(maker, tmp_path)
        await bot.send(message_update("/photo"))
        before = await user_credits(maker)

        await no(bot)

        assert not feat.provider.calls and not bot.session.named("SendPhoto")
        assert bot.session.named("DeleteMessage")
        assert await user_credits(maker) == before

    run_db(scenario)


def test_pressing_yes_twice_pays_once(run_db, tmp_path, credits_on):
    async def scenario(maker):
        bot, feat = await started(maker, tmp_path)
        await bot.send(message_update("/photo"))

        await yes(bot)
        await yes(bot)

        assert len(feat.provider.calls) == 1 and len(bot.session.named("SendPhoto")) == 1
        assert await user_credits(maker) == 5
        assert bot.session.named("AnswerCallbackQuery")[-1]["text"] == t("en", "img_expired")

    run_db(scenario)


def test_an_unknown_offer_is_expired(run_db, tmp_path):
    async def scenario(maker):
        bot, feat = await started(maker, tmp_path)
        await yes(bot)  # nothing was offered
        assert not feat.provider.calls
        assert bot.session.named("AnswerCallbackQuery")[-1]["text"] == t("en", "img_expired")

    run_db(scenario)


def test_too_few_credits_keeps_the_offer_for_later(run_db, tmp_path, credits_on):
    async def scenario(maker):
        bot, feat = await started(maker, tmp_path)
        await bot.send(message_update("hello"))  # the free trial is given on the first paid action
        await bot.send(message_update("/photo"))
        await set_credits(maker, 2)

        await yes(bot)
        assert not feat.provider.calls
        assert bot.session.named("AnswerCallbackQuery")[-1]["text"] == t("en", "credits_empty", cost=5, credits=2)
        assert await user_credits(maker) == 2

        await set_credits(maker, 9)
        await yes(bot)  # the same offer still works
        assert len(feat.provider.calls) == 1 and await user_credits(maker) == 4

    run_db(scenario)


@pytest.mark.parametrize(
    "provider_class,key",
    [(BrokenImageProvider, "img_failed"), (RefusingImageProvider, "img_refused")],
)
def test_a_failed_picture_is_refunded_and_explained(run_db, tmp_path, credits_on, provider_class, key):
    async def scenario(maker):
        bot, feat = await started(maker, tmp_path, image_provider=provider_class())
        await bot.send(message_update("/photo"))

        await yes(bot)

        assert await user_credits(maker) == 10
        assert not bot.session.named("SendPhoto") and await image_messages(maker) == 0
        edits = [d["text"] for d in bot.session.named("EditMessageText")]
        assert edits[-1] == t("en", key, name="Amy")

    run_db(scenario)


def test_a_telegram_upload_failure_is_refunded_too(run_db, tmp_path, credits_on):
    async def scenario(maker):
        bot, feat = await started(maker, tmp_path)
        await bot.send(message_update("/photo"))
        bot.session.photo_error = "wrong file"

        await yes(bot)

        assert await user_credits(maker) == 10
        assert bot.session.named("EditMessageText")[-1]["text"] == t("en", "img_failed", name="Amy")

    run_db(scenario)


def test_asking_in_the_chat_gets_a_reply_and_then_one_offer(run_db, tmp_path):
    async def scenario(maker):
        bot, feat = await started(maker, tmp_path)

        await bot.send(message_update("bana bir fotoğraf at"))
        assert "ok" in bot.texts()[-2]  # her normal answer comes first
        assert bot.texts()[-1] == t("en", "img_offer_free", name="Amy")

        before = len(bot.texts())
        await bot.send(message_update("send me a pic please"))
        assert len(bot.texts()) == before + 1  # the reply only: no second offer inside the cooldown

    run_db(scenario)


def test_ordinary_chat_and_groups_never_trigger_an_offer(run_db, tmp_path):
    async def scenario(maker):
        bot, _ = await started(maker, tmp_path)
        await bot.send(message_update("bugün hava çok güzel"))
        assert t("en", "img_offer_free", name="Amy") not in bot.texts()

        await bot.send(message_update("/newgroup"))
        await bot.send(callback_update("gsel:0:amy"))
        await bot.send(callback_update("gsel:0:bob"))
        await bot.send(callback_update("gdone"))
        await bot.send(message_update("send me a photo"))
        assert t("en", "img_offer_free", name="Amy") not in bot.texts()

    run_db(scenario)


def test_the_same_scene_is_shared_but_costs_the_second_user_the_same(run_db, tmp_path, credits_on):
    async def scenario(maker):
        bot, feat = await started(maker, tmp_path)
        await bot.send(message_update("/photo"))
        await yes(bot)
        await bot.send(message_update("/photo"))
        await yes(bot)
        assert len(feat.provider.calls) == 2  # two variants are made first
        async with maker() as s:
            assert (await s.execute(select(func.count()).select_from(ImageCacheEntry))).scalar_one() == 2

    run_db(scenario)


def test_someone_elses_offer_is_not_accepted(run_db, tmp_path, credits_on):
    import dataclasses
    import uuid

    async def scenario(maker):
        bot, feat = await started(maker, tmp_path)
        await bot.send(message_update("/photo"))
        offers = bot.dispatcher.workflow_data["offers"]
        key = (1001, OFFER_MESSAGE_ID)
        offers._offers[key] = dataclasses.replace(offers._offers[key], user_id=uuid.uuid4())

        await yes(bot)

        assert not feat.provider.calls and not bot.session.named("SendPhoto")
        assert bot.session.named("AnswerCallbackQuery")[-1]["text"] == t("en", "img_expired")

    run_db(scenario)


def test_a_subscriber_still_pays_credits_for_a_picture(run_db, tmp_path, credits_on):
    from datetime import datetime, timedelta, timezone

    from app.services.credit_service import CreditConfig, CreditService

    async def scenario(maker):
        bot, feat = await started(maker, tmp_path)
        await bot.send(message_update("hello"))  # the free trial is given on the first paid action
        async with maker() as s:
            user = (await s.execute(select(User).where(User.telegram_id == 1001))).scalar_one()
            await CreditService(s, CreditConfig(enabled=True)).set_subscription(
                user.id, datetime.now(timezone.utc) + timedelta(days=5)
            )
        before = await user_credits(maker)
        await bot.send(message_update("/photo"))

        await yes(bot)

        assert len(feat.provider.calls) == 1
        assert await user_credits(maker) == before - 5

    run_db(scenario)


def test_an_operator_gets_pictures_without_credits(run_db, tmp_path, credits_on, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_TELEGRAM_IDS", "1001")

    async def scenario(maker):
        bot, feat = await started(maker, tmp_path)
        await bot.send(message_update("/photo"))
        await set_credits(maker, 0)

        await yes(bot)

        assert len(feat.provider.calls) == 1 and len(bot.session.named("SendPhoto")) == 1
        assert await user_credits(maker) == 0

    run_db(scenario)
