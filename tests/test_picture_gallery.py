"""The user's own picture gallery: /gallery and the ‹ n/total › slider."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.config import settings
from app.models import Character, Conversation, Message, User
from app.services.picture_gallery_service import PictureGalleryService
from app.telegram import keyboards
from app.telegram.texts import t
from tests.image_fakes import PNG_HEAD
from tests.telegram_harness import Harness, callback_update, message_update
from tests.test_image_flow import PEOPLE, feature, started
from tests.image_fakes import SceneProvider
from tests.telegram_harness import add_characters

BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


async def seed(maker, feat, telegram_id, slug, names, *, save=True, start=0):
    """Give a user pictures (oldest first); returns the stored keys."""
    keys = []
    async with maker() as s:
        user = (await s.execute(select(User).where(User.telegram_id == telegram_id))).scalar_one()
        conv = (await s.execute(select(Conversation).where(Conversation.user_id == user.id))).scalars().first()
        char = (await s.execute(select(Character).where(Character.slug == slug))).scalar_one()
        for i, name in enumerate(names):
            key = await feat.storage.save(PNG_HEAD + name.encode(), "png") if save else f"gone-{name}.png"
            keys.append(key)
            s.add(
                Message(
                    conversation_id=conv.id,
                    sender_type="character",
                    sender_character_id=char.id,
                    content="*sends you a photo*",
                    message_type="image",
                    image_key=key,
                    created_at=BASE + timedelta(days=start + i),
                )
            )
        await s.commit()
    return keys


def pic_buttons(bot, call="SendPhoto"):
    markup = bot.session.named(call)[-1].get("reply_markup")
    return [b["callback_data"] for row in markup["inline_keyboard"] for b in row] if markup else []


def test_gallery_shows_newest_first_with_a_slider(run_db, tmp_path):
    async def scenario(run_db):
        bot, feat = await started(run_db, tmp_path)
        await seed(run_db, feat, 1001, "amy", ["a", "b", "c"])
        await bot.send(message_update("/gallery"))
        sent = bot.session.named("SendPhoto")
        assert len(sent) == 1
        assert "Amy" in sent[0]["caption"] and "03.01.2026" in sent[0]["caption"] and "1/3" in sent[0]["caption"]
        assert pic_buttons(bot) == ["pic:2", "noop", "pic:1"]

    run_db(scenario)


def test_the_slider_moves_and_wraps_around(run_db, tmp_path):
    async def scenario(run_db):
        bot, feat = await started(run_db, tmp_path)
        await seed(run_db, feat, 1001, "amy", ["a", "b", "c"])
        await bot.send(callback_update("pic:1", has_photo=True))
        edit = bot.session.named("EditMessageMedia")[-1]
        assert "2/3" in edit["media"]["caption"] and "02.01.2026" in edit["media"]["caption"]
        await bot.send(callback_update("pic:3", has_photo=True))  # past the end -> first
        assert "1/3" in bot.session.named("EditMessageMedia")[-1]["media"]["caption"]
        await bot.send(callback_update("pic:-1", has_photo=True))  # before the start -> last
        assert "3/3" in bot.session.named("EditMessageMedia")[-1]["media"]["caption"]

    run_db(scenario)


def test_one_picture_has_no_slider(run_db, tmp_path):
    async def scenario(run_db):
        bot, feat = await started(run_db, tmp_path)
        await seed(run_db, feat, 1001, "amy", ["a"])
        await bot.send(message_update("/gallery"))
        assert pic_buttons(bot) == []

    run_db(scenario)


def test_empty_gallery_points_to_the_photo_button(run_db, tmp_path):
    async def scenario(run_db):
        bot, _ = await started(run_db, tmp_path)
        await bot.send(message_update("/gallery"))
        assert not bot.session.named("SendPhoto")
        assert t("en", "pic_empty") in bot.texts()

    run_db(scenario)


def test_pictures_off_says_so(run_db, tmp_path):
    async def scenario(run_db):
        bot, _ = await started(run_db, tmp_path, images=False)
        await bot.send(message_update("/gallery"))
        assert t("en", "img_off") in bot.texts()
        await bot.send(callback_update("pic:0", has_photo=True))
        assert not bot.session.named("EditMessageMedia")

    run_db(scenario)


def test_a_user_only_sees_their_own_pictures(run_db, tmp_path):
    async def scenario(run_db):
        bot, feat = await started(run_db, tmp_path)
        await bot.send(callback_update("open:bob", user_id=2002, first="Eve"))
        await seed(run_db, feat, 1001, "amy", ["mine1", "mine2"])
        await seed(run_db, feat, 2002, "bob", ["theirs"])
        async with run_db() as s:
            ids = {u.telegram_id: u.id for u in (await s.execute(select(User))).scalars()}
            mine = await PictureGalleryService(s).list_for_user(ids[1001])
            theirs = await PictureGalleryService(s).list_for_user(ids[2002])
        assert [p.character_name for p in mine] == ["Amy", "Amy"]
        assert [p.character_name for p in theirs] == ["Bob"]
        await bot.send(callback_update("pic:0", has_photo=True))
        assert "1/2" in bot.session.named("EditMessageMedia")[-1]["media"]["caption"]
        await bot.send(callback_update("pic:5", has_photo=True))  # never reaches user 2002's picture
        assert "/2" in bot.session.named("EditMessageMedia")[-1]["media"]["caption"]

    run_db(scenario)


def test_a_missing_file_is_skipped(run_db, tmp_path):
    async def scenario(run_db):
        bot, feat = await started(run_db, tmp_path)
        await seed(run_db, feat, 1001, "amy", ["old"], start=0)
        await seed(run_db, feat, 1001, "amy", ["gone"], save=False, start=5)  # newest, file lost
        await bot.send(message_update("/gallery"))
        caption = bot.session.named("SendPhoto")[-1]["caption"]
        assert "2/2" in caption  # fell through to the one that still exists

    run_db(scenario)


def test_all_files_missing_gives_the_empty_text(run_db, tmp_path):
    async def scenario(run_db):
        bot, feat = await started(run_db, tmp_path)
        await seed(run_db, feat, 1001, "amy", ["gone"], save=False)
        await bot.send(message_update("/gallery"))
        assert not bot.session.named("SendPhoto")
        assert t("en", "pic_empty") in bot.texts()
        await bot.send(callback_update("pic:0", has_photo=True))
        assert not bot.session.named("EditMessageMedia")

    run_db(scenario)


def test_text_messages_are_not_pictures(run_db, tmp_path):
    async def scenario(run_db):
        bot, feat = await started(run_db, tmp_path)
        await bot.send(message_update("hello"))
        await bot.send(message_update("/gallery"))
        assert not bot.session.named("SendPhoto")

    run_db(scenario)


def test_menu_has_the_gallery_button_only_with_pictures_on(monkeypatch):
    def labels():
        return [b.text for row in keyboards.main_menu("en").keyboard for b in row]

    monkeypatch.setattr(settings, "IMAGES_ENABLED", False)
    assert t("en", "menu_pictures") not in labels()
    monkeypatch.setattr(settings, "IMAGES_ENABLED", True)
    assert t("en", "menu_pictures") in labels()


def test_the_menu_button_opens_the_gallery(run_db, tmp_path):
    async def scenario(run_db):
        bot, feat = await started(run_db, tmp_path)
        await seed(run_db, feat, 1001, "amy", ["a", "b"])
        await bot.send(message_update(t("en", "menu_pictures")))
        assert len(bot.session.named("SendPhoto")) == 1

    run_db(scenario)


def test_a_lost_file_before_the_end_wraps_to_the_start(run_db, tmp_path):
    async def scenario(run_db):
        bot, feat = await started(run_db, tmp_path)
        await seed(run_db, feat, 1001, "amy", ["gone"], save=False, start=0)  # oldest = last slide
        await seed(run_db, feat, 1001, "amy", ["new"], start=5)
        await bot.send(callback_update("pic:1", has_photo=True))
        assert "1/2" in bot.session.named("EditMessageMedia")[-1]["media"]["caption"]

    run_db(scenario)


def test_only_real_pictures_are_listed(run_db, tmp_path):
    async def scenario(run_db):
        bot, feat = await started(run_db, tmp_path)
        key = await feat.storage.save(PNG_HEAD + b"x", "png")
        async with run_db() as s:
            user = (await s.execute(select(User).where(User.telegram_id == 1001))).scalar_one()
            conv = (await s.execute(select(Conversation).where(Conversation.user_id == user.id))).scalars().first()
            char = (await s.execute(select(Character).where(Character.slug == "amy"))).scalar_one()
            base = dict(conversation_id=conv.id, sender_type="character", sender_character_id=char.id, content="x")
            s.add(Message(**base, message_type="image", image_key=None))  # picture without a file
            s.add(Message(**base, message_type="text", image_key=key))  # not a picture message
            await s.commit()
            assert await PictureGalleryService(s).list_for_user(user.id) == []

    run_db(scenario)
