"""Pictures in groups (the user picks who) and "Create art" (own description)."""

import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.models import ImageCacheEntry, Message
from app.services.image_service import ImageService
from app.services.image_scene import MAX_ART_CHARS, clean_art_text
from app.telegram import keyboards
from app.telegram.photo_offers import PhotoOffers
from app.telegram.texts import t
from tests.image_fakes import FakeImageProvider, FakeLoader, RefusingImageProvider, SceneProvider, definition
from tests.telegram_harness import Harness, add_characters, callback_update, message_update
from tests.test_image_flow import PEOPLE, feature, image_messages, no, started, user_credits, yes


@pytest.fixture
def credits_on(monkeypatch):
    monkeypatch.setattr(settings, "CREDITS_ENABLED", True)
    monkeypatch.setattr(settings, "TRIAL_CREDITS", 20)
    monkeypatch.setattr(settings, "IMAGE_COST", 5)
    monkeypatch.setattr(settings, "ART_COST", 10)
    monkeypatch.setattr(settings, "GROUP_CREATE_COST", 0)


async def group_chat(bot):
    await bot.send(message_update("/newgroup"))
    await bot.send(callback_update("gsel:0:amy"))
    await bot.send(callback_update("gsel:0:bob"))
    await bot.send(callback_update("gdone"))


def last_buttons(bot):
    return bot.callback_data("SendMessage")


def ask_reply(text):
    return message_update(text, reply_to=t("en", "art_ask"))


# ------------------------------------------------------------ group photos


def test_group_photo_asks_who_and_lists_only_drawable_members(run_db, tmp_path):
    async def scenario(maker):
        loader = FakeLoader(definition("amy", "Amy"))  # Bob cannot be drawn
        bot, _ = await started(maker, tmp_path, loader=loader)
        await group_chat(bot)
        await bot.send(message_update("/photo"))
        assert bot.texts()[-1] == t("en", "img_pick")
        assert last_buttons(bot) == ["imgp:amy"]

    run_db(scenario)


def test_group_photo_with_nobody_drawable_says_so(run_db, tmp_path):
    async def scenario(maker):
        bot, _ = await started(maker, tmp_path, loader=FakeLoader())
        await group_chat(bot)
        await bot.send(message_update("/photo"))
        assert bot.texts()[-1] == t("en", "img_pick_none")

    run_db(scenario)


def test_group_photo_is_made_by_the_chosen_member(run_db, tmp_path, credits_on):
    async def scenario(maker):
        bot, feat = await started(maker, tmp_path)
        await group_chat(bot)
        await bot.send(message_update("/photo"))
        await bot.send(callback_update("imgp:bob"))
        assert bot.texts()[-1] == t("en", "img_offer", name="Bob", cost=5)

        await yes(bot)

        assert [ref for _, ref in feat.provider.calls] == ["xav-bob-12345"]
        assert len(bot.session.named("SendPhoto")) == 1
        assert await user_credits(maker) == 15
        async with maker() as s:
            from app.models import Character

            sender = (
                await s.execute(
                    select(Character.slug)
                    .join(Message, Message.sender_character_id == Character.id)
                    .where(Message.message_type == "image")
                )
            ).scalar_one()
        assert sender == "bob"

    run_db(scenario)


def test_picking_someone_outside_the_group_is_refused(run_db, tmp_path):
    async def scenario(maker):
        await add_characters(maker, [("Cy", "cy", 2, True)])
        bot, feat = await started(maker, tmp_path)
        await group_chat(bot)
        await bot.send(callback_update("imgp:cy"))
        assert t("en", "img_offer_free", name="Cy") not in bot.texts()
        assert not feat.provider.calls

    run_db(scenario)


# --------------------------------------------------------------- create art


def test_art_asks_then_offers_with_its_own_price(run_db, tmp_path, credits_on):
    async def scenario(maker):
        bot, _ = await started(maker, tmp_path)
        await bot.send(message_update("/art"))
        assert bot.texts()[-1] == t("en", "art_ask")
        assert "force_reply" in str(bot.session.named("SendMessage")[-1]["reply_markup"])
        await bot.send(ask_reply("a knight on a dragon"))
        assert bot.texts()[-1] == t("en", "art_offer", name="Amy", cost=10)

    run_db(scenario)


def test_art_sends_the_users_text_and_is_never_cached(run_db, tmp_path, credits_on):
    async def scenario(maker):
        chat = SceneProvider(chat_reply="ok")
        bot, feat = await started(maker, tmp_path, chat=chat)
        for _ in range(2):
            await bot.send(message_update("/art"))
            await bot.send(ask_reply("a knight on a dragon"))
            await yes(bot)
        assert [p for p, _ in feat.provider.calls] == ["a knight on a dragon"] * 2  # no reuse
        assert not chat.scene_requests  # no scene-writer call (saves tokens)
        assert await user_credits(maker) == 0  # 20 trial - 2 x 10
        assert await image_messages(maker) == 2
        async with maker() as s:
            assert (await s.execute(select(func.count()).select_from(ImageCacheEntry))).scalar_one() == 0

    run_db(scenario)


def test_art_text_is_cleaned_and_capped(run_db, tmp_path):
    async def scenario(maker):
        bot, feat = await started(maker, tmp_path)
        await bot.send(message_update("/art"))
        await bot.send(ask_reply("a\x00 b\x07\n  c " + "x" * 1000))
        await yes(bot)
        prompt = feat.provider.calls[0][0]
        assert prompt.startswith("a b c x") and len(prompt) == MAX_ART_CHARS
        assert "\x00" not in prompt and "\n" not in prompt

    run_db(scenario)


def test_art_refused_by_the_image_service_refunds(run_db, tmp_path, credits_on):
    async def scenario(maker):
        bot, _ = await started(maker, tmp_path, image_provider=RefusingImageProvider())
        await bot.send(message_update("/art"))
        await bot.send(ask_reply("anything"))
        await yes(bot)
        assert await user_credits(maker) == 20
        assert t("en", "img_refused", name="Amy") in [
            d["text"] for d in bot.session.named("EditMessageText")
        ]
        assert not bot.session.named("SendPhoto")

    run_db(scenario)


def test_art_no_costs_nothing(run_db, tmp_path, credits_on):
    async def scenario(maker):
        bot, feat = await started(maker, tmp_path)
        await bot.send(message_update("/art"))
        await bot.send(ask_reply("a cat"))
        await no(bot)
        assert not feat.provider.calls

    run_db(scenario)


def test_a_reply_without_a_pending_question_is_not_art(run_db, tmp_path):
    async def scenario(maker):
        bot, feat = await started(maker, tmp_path)
        await bot.send(ask_reply("a cat"))
        assert bot.texts()[-1] == t("en", "img_expired")
        assert not feat.provider.calls

    run_db(scenario)


def test_a_blank_description_is_not_offered(run_db, tmp_path):
    async def scenario(maker):
        bot, _ = await started(maker, tmp_path)
        await bot.send(message_update("/art"))
        await bot.send(ask_reply("\x00\x01  "))
        assert bot.texts()[-1] == t("en", "art_invalid")

    run_db(scenario)


def test_art_is_for_characters_that_can_be_drawn(run_db, tmp_path):
    async def scenario(maker):
        bot, _ = await started(maker, tmp_path, loader=FakeLoader())
        await bot.send(message_update("/art"))
        assert bot.texts()[-1] == t("en", "img_unavailable", name="Amy")

    run_db(scenario)


def test_art_in_a_group_picks_the_member_first(run_db, tmp_path, credits_on):
    async def scenario(maker):
        bot, feat = await started(maker, tmp_path)
        await group_chat(bot)
        await bot.send(message_update("/art"))
        assert bot.texts()[-1] == t("en", "art_pick")
        assert last_buttons(bot) == ["imga:amy", "imga:bob"]
        await bot.send(callback_update("imga:bob"))
        assert bot.texts()[-1] == t("en", "art_ask")
        await bot.send(ask_reply("a sunset"))
        assert bot.texts()[-1] == t("en", "art_offer", name="Bob", cost=10)
        await yes(bot)
        assert feat.provider.calls == [("a sunset", "xav-bob-12345")]

    run_db(scenario)


def test_art_off_and_no_chat(run_db, tmp_path):
    async def scenario(maker):
        bot, _ = await started(maker, tmp_path, images=False)
        await bot.send(message_update("/art"))
        assert bot.texts()[-1] == t("en", "img_off")

    run_db(scenario)


def test_the_art_ask_expires():
    now = [0.0]
    offers = PhotoOffers(ttl=10, clock=lambda: now[0])
    offers.ask_art("u", "c", None)
    now[0] = 11
    assert offers.take_art_ask("u") is None
    offers.ask_art("u", "c", "amy")
    assert offers.take_art_ask("u").character_slug == "amy"
    assert offers.take_art_ask("u") is None  # taken once


def test_clean_art_text():
    assert clean_art_text(None) is None and clean_art_text(" \n\x00 ") is None
    assert clean_art_text("  a   b ") == "a b"


def test_menu_has_the_art_button_only_with_pictures_on(monkeypatch):
    def labels():
        return [b.text for row in keyboards.main_menu("en").keyboard for b in row]

    monkeypatch.setattr(settings, "IMAGES_ENABLED", False)
    assert t("en", "menu_art") not in labels()
    monkeypatch.setattr(settings, "IMAGES_ENABLED", True)
    assert t("en", "menu_art") in labels()


def test_art_is_booked_as_art_not_as_a_photo(run_db, tmp_path, credits_on):
    async def scenario(maker):
        from app.models import CreditTransaction

        bot, _ = await started(maker, tmp_path)
        await bot.send(message_update("/art"))
        await bot.send(ask_reply("a cat"))
        await yes(bot)
        async with maker() as s:
            reasons = (await s.execute(select(CreditTransaction.reason))).scalars().all()
        assert "art" in reasons and "image" not in reasons

    run_db(scenario)


def test_one_description_makes_one_offer(run_db, tmp_path):
    async def scenario(maker):
        bot, _ = await started(maker, tmp_path)
        await bot.send(message_update("/art"))
        await bot.send(ask_reply("a cat"))
        await bot.send(ask_reply("a dog"))  # the question was already answered
        assert bot.texts()[-1] == t("en", "img_expired")

    run_db(scenario)


def test_a_description_for_another_chat_is_dropped(run_db, tmp_path):
    async def scenario(maker):
        bot, feat = await started(maker, tmp_path)
        await bot.send(message_update("/art"))
        await bot.send(callback_update("open:bob"))  # now another chat is active
        await bot.send(ask_reply("a cat"))
        assert bot.texts()[-1] == t("en", "img_expired")
        assert not feat.provider.calls

    run_db(scenario)


def test_group_buttons_for_a_stranger_do_nothing(run_db, tmp_path):
    async def scenario(maker):
        await add_characters(maker, [("Cy", "cy", 2, True)])
        loader = FakeLoader(
            definition("amy", "Amy"), definition("bob", "Bob", image_id="xav-bob-12345"),
            definition("cy", "Cy", image_id="xav-cy-12345"),
        )
        bot, _ = await started(maker, tmp_path, loader=loader)
        await group_chat(bot)
        for data in ("imgp:cy", "imga:cy"):
            await bot.send(callback_update(data))
        alerts = [c for c in bot.session.named("AnswerCallbackQuery") if c.get("show_alert")]
        assert len(alerts) == 2
        await bot.send(ask_reply("a cat"))  # no question was opened
        assert bot.texts()[-1] == t("en", "img_expired")

    run_db(scenario)


def test_the_service_itself_refuses_an_undrawable_character(run_db, tmp_path):
    async def scenario(maker):
        from app.models import Conversation, User
        from app.services.image_prompt_builder import ImageNotAvailable

        bot, feat = await started(maker, tmp_path)
        underage_loader = FakeLoader(definition("amy", "Amy", age=0), definition("bob", "Bob"))
        feat = feature(tmp_path, loader=underage_loader)  # no adult age in the YAML
        async with maker() as s:
            user = (await s.execute(select(User))).scalar_one()
            conv = (await s.execute(select(Conversation))).scalars().first()
            with pytest.raises(ImageNotAvailable):
                await ImageService(s, feat, SceneProvider()).generate(conv.id, user.id, None, art_text="a cat")
        assert not feat.provider.calls

    run_db(scenario)
