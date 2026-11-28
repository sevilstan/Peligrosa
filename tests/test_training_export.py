"""Training exports leave out everyone who deleted their data."""

import json
import uuid

import pytest
from sqlalchemy import select

from app.models import Conversation, Message, User
from app.services.training_export_service import TrainingExportService, pseudonym
from app.services.user_data_service import UserDataService, extract_user_ids
from app.telegram.texts import t
from tests.telegram_harness import Harness, add_characters, callback_update, message_update

SALT = "a-private-salt-of-enough-length"
PEOPLE = [("Amy", "amy", 0, True)]


async def talk(bot, user_id, first, text):
    await bot.send(callback_update("open:amy", user_id=user_id, first=first))
    await bot.send(message_update(text, user_id=user_id, first=first))


async def export(maker):
    async with maker() as s:
        return [r async for r in TrainingExportService(s, SALT).conversations()]


async def uid(maker, telegram_id):
    async with maker() as s:
        return (await s.execute(select(User.id).where(User.telegram_id == telegram_id))).scalar_one()


def test_pseudonyms_are_stable_salted_and_need_a_real_salt():
    value = uuid.uuid4()
    assert pseudonym(SALT, value) == pseudonym(SALT, value)
    assert pseudonym(SALT, value) != pseudonym(SALT + "x", value)
    assert pseudonym(SALT, value) != pseudonym(SALT, uuid.uuid4())
    assert str(value) not in pseudonym(SALT, value)
    for bad in ("", "short", None):
        with pytest.raises(ValueError):
            pseudonym(bad, value)


def test_export_has_chats_but_no_identities(run_db, tmp_path):
    async def scenario(maker):
        await add_characters(maker, PEOPLE)
        bot = Harness(maker, tmp_path)
        await talk(bot, 1001, "Ada", "hello from ada")

        records = await export(maker)
        assert len(records) == 1
        record = records[0]
        assert record["type"] == "direct"
        roles = [(m["role"], m["character"]) for m in record["messages"]]
        assert roles == [("user", None), ("character", "amy")]
        assert record["messages"][0]["content"] == "hello from ada"

        text = json.dumps(records)
        for secret in ("1001", "Ada", str(await uid(maker, 1001))):
            assert secret not in text.replace("hello from ada", ""), secret
        assert record["user"] == pseudonym(SALT, await uid(maker, 1001))

    run_db(scenario)


def test_deleted_users_leave_the_export_and_are_listed(run_db, tmp_path):
    async def scenario(maker):
        await add_characters(maker, PEOPLE)
        bot = Harness(maker, tmp_path)
        await talk(bot, 1001, "Ada", "ada text")
        await talk(bot, 2002, "Eve", "eve text")
        assert len(await export(maker)) == 2

        async with maker() as s:  # an operator wipes a user's data (no user command exists)
            await UserDataService(s).delete_all(await uid(maker, 1001))

        records = await export(maker)
        assert [r["messages"][0]["content"] for r in records] == ["eve text"]
        async with maker() as s:
            assert await TrainingExportService(s, SALT).deleted_pseudonyms() == [
                pseudonym(SALT, await uid(maker, 1001))
            ]

    run_db(scenario)


def test_deactivated_users_are_not_exported(run_db, tmp_path):
    async def scenario(maker):
        await add_characters(maker, PEOPLE)
        bot = Harness(maker, tmp_path)
        await talk(bot, 1001, "Ada", "ada text")
        async with maker() as s:
            (await s.execute(select(User))).scalar_one().is_active = False
            await s.commit()
        assert await export(maker) == []

    run_db(scenario)


def test_a_missing_salt_stops_the_export(run_db):
    async def scenario(maker):
        async with maker() as s:
            with pytest.raises(ValueError):
                TrainingExportService(s, "")

    run_db(scenario)


# ------------------------------------------------------- re-applying deletions


def test_user_ids_are_found_in_plain_lists_and_log_lines():
    a, b = uuid.uuid4(), uuid.uuid4()
    text = (
        f"2026-11-25 INFO app.telegram.handlers: User data deleted: user_id={a} chats=2\n"
        f"{b}\n"
        f"duplicate {a}\nnot an id: 1234\n"
    )
    assert extract_user_ids(text) == [a, b]
    assert extract_user_ids("") == []


def test_a_restored_backup_can_be_cleaned_again(run_db, tmp_path):
    """Simulates restoring an old backup: data is back, deletion is re-applied."""

    async def scenario(maker):
        await add_characters(maker, PEOPLE)
        bot = Harness(maker, tmp_path)
        await talk(bot, 1001, "Ada", "ada text")
        user_id = await uid(maker, 1001)

        async with maker() as s:  # the "backup" still has the data and no deletion mark
            assert (await s.execute(select(Message))).scalars().all()
            user = (await s.execute(select(User).where(User.id == user_id))).scalar_one()
            assert user.data_deleted_at is None

        async with maker() as s:
            await UserDataService(s).delete_all(user_id)
        async with maker() as s:
            assert (await s.execute(select(Conversation))).scalars().all() == []
            assert (await s.execute(select(User).where(User.id == user_id))).scalar_one().data_deleted_at

    run_db(scenario)


def test_terms_tell_users_about_training_and_how_to_delete_a_chat():
    assert "train" in t("en", "terms_text") and "eğit" in t("tr", "terms_text")
    for language in ("en", "tr"):
        text = t(language, "terms_text")
        assert "/delete" in text and "/support" in text and "/deletedata" not in text


def test_the_deleted_mark_alone_keeps_a_user_out_of_the_export(run_db, tmp_path):
    """Safety net: if old data ever comes back (e.g. a restored backup) for a
    user marked as deleted, it must still not reach a training set."""
    from datetime import datetime, timezone

    async def scenario(maker):
        await add_characters(maker, PEOPLE)
        bot = Harness(maker, tmp_path)
        await talk(bot, 1001, "Ada", "ada text")
        assert len(await export(maker)) == 1

        async with maker() as s:
            (await s.execute(select(User))).scalar_one().data_deleted_at = datetime.now(timezone.utc)
            await s.commit()

        assert await export(maker) == []

    run_db(scenario)


def test_pictures_are_not_part_of_the_training_export(run_db, tmp_path):
    async def scenario(maker):
        await add_characters(maker, PEOPLE)
        bot = Harness(maker, tmp_path)
        await talk(bot, 1001, "Ada", "hello")
        async with maker() as s:
            conversation = (await s.execute(select(Conversation))).scalars().first()
            character_id = (await s.execute(select(Message.sender_character_id).where(Message.sender_type == "character"))).scalars().first()
            s.add(
                Message(
                    conversation_id=conversation.id,
                    sender_type="character",
                    sender_character_id=character_id,
                    content="*sends you a photo*",
                    message_type="image",
                    image_key="abc.png",
                )
            )
            await s.commit()

        records = await export(maker)

        contents = [m["content"] for m in records[0]["messages"]]
        assert "*sends you a photo*" not in contents and len(contents) == 2

    run_db(scenario)
