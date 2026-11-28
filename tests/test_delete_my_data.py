"""Wiping a user's data is an operator tool (UserDataService), not a user command.

Users can only delete a chat with a character (/delete). Credits, payments and
other accounting records stay out of reach of that.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.models import (
    Character,
    CharacterEmotion,
    CharacterMemory,
    CharacterRelationship,
    Conversation,
    CreditTransaction,
    Message,
    StarPayment,
    User,
    UserMemory,
)
from app.services.user_data_service import UserDataService
from app.telegram import bot as bot_module
from app.telegram.keyboards import DELETE_CONFIRM_PREFIX
from app.telegram.texts import t
from tests.telegram_harness import Harness, add_characters, callback_update, message_update

PEOPLE = [("Amy", "amy", 0, True), ("Bob", "bob", 1, True)]


async def count(maker, model, **filters):
    async with maker() as s:
        query = select(func.count()).select_from(model)
        for column, value in filters.items():
            query = query.where(getattr(model, column) == value)
        return (await s.execute(query)).scalar_one()


async def user_id(maker, telegram_id):
    async with maker() as s:
        return (await s.execute(select(User.id).where(User.telegram_id == telegram_id))).scalar_one()


async def seed_state(maker, uid):
    """Memories, relationship and mood for one user (both characters exist)."""
    async with maker() as s:
        chars = (await s.execute(select(Character).order_by(Character.sort_order))).scalars().all()
        a, b = chars[0].id, chars[1].id
        s.add(CharacterMemory(user_id=uid, character_id=a, category="interest", content="likes sci-fi"))
        s.add(CharacterMemory(user_id=uid, character_id=b, category="hobby", content="plays chess"))
        s.add(UserMemory(user_id=uid, category="personal", content="lives in Izmir"))
        s.add(CharacterRelationship(user_id=uid, character_id=a, other_character_id=b, trust=70))
        s.add(CharacterEmotion(user_id=uid, character_id=a, mood="happy", intensity=60))
        await s.commit()


async def chat_with(bot, text="hello there"):
    await bot.send(callback_update("open:amy"))
    await bot.send(message_update(text))


def test_everything_personal_is_deleted(run_db, tmp_path):
    async def scenario(maker):
        await add_characters(maker, PEOPLE)
        bot = Harness(maker, tmp_path)
        await chat_with(bot)
        uid = await user_id(maker, 1001)
        await seed_state(maker, uid)
        assert await count(maker, Message) > 0

        async with maker() as s:
            await UserDataService(s).delete_all(uid)

        for model in (Conversation, Message, CharacterMemory, UserMemory, CharacterRelationship, CharacterEmotion):
            assert await count(maker, model) == 0, model.__name__

        # The user can simply start again.
        await chat_with(bot, "hi again")
        assert await count(maker, Conversation) == 1

    run_db(scenario)


def test_other_users_keep_everything(run_db, tmp_path):
    async def scenario(maker):
        await add_characters(maker, PEOPLE)
        bot = Harness(maker, tmp_path)
        await chat_with(bot)
        await bot.send(callback_update("open:amy", user_id=2002, first="Eve"))
        await bot.send(message_update("eve here", user_id=2002, first="Eve"))
        await seed_state(maker, await user_id(maker, 1001))
        await seed_state(maker, await user_id(maker, 2002))
        eve = await user_id(maker, 2002)
        mine = await user_id(maker, 1001)
        eve_counts = {
            m: await count(maker, m, user_id=eve)
            for m in (CharacterMemory, UserMemory, CharacterRelationship, CharacterEmotion, Conversation)
        }
        eve_messages = await count(maker, Message)

        async with maker() as s:
            await UserDataService(s).delete_all(mine)

        for model, expected in eve_counts.items():
            assert await count(maker, model, user_id=eve) == expected, model.__name__
        assert await count(maker, Message) < eve_messages  # only 1001's went
        assert await count(maker, Message, sender_user_id=eve) >= 1

    run_db(scenario)


def test_account_credits_and_payments_stay(run_db, tmp_path):
    async def scenario(maker):
        await add_characters(maker, PEOPLE)
        bot = Harness(maker, tmp_path)
        await chat_with(bot)
        uid = await user_id(maker, 1001)
        async with maker() as s:
            user = (await s.execute(select(User).where(User.id == uid))).scalar_one()
            user.credits = 77
            user.trial_granted_at = datetime.now(timezone.utc)
            user.subscription_until = datetime.now(timezone.utc) + timedelta(days=9)
            s.add(StarPayment(user_id=uid, telegram_charge_id="c1", product="sub", stars=400))
            s.add(CreditTransaction(user_id=uid, amount=77, balance_after=77, reason="admin_grant"))
            await s.commit()

        async with maker() as s:
            await UserDataService(s).delete_all(uid)

        async with maker() as s:
            user = (await s.execute(select(User).where(User.id == uid))).scalar_one()
            assert user.credits == 77 and user.trial_granted_at is not None
            assert user.subscription_until is not None
        assert await count(maker, StarPayment) == 1
        assert await count(maker, CreditTransaction) == 1

    run_db(scenario)


def test_welcome_mentions_ai_and_adults_only():
    welcome = t("en", "welcome")
    assert "AI" in welcome and "18+" in welcome and "/terms" in welcome
    assert "18+" in t("tr", "welcome")


def test_deletion_is_all_or_nothing(run_db, tmp_path):
    from app.services.user_data_service import UserDataService

    async def scenario(maker):
        await add_characters(maker, PEOPLE)
        bot = Harness(maker, tmp_path)
        await chat_with(bot)
        uid = await user_id(maker, 1001)
        await seed_state(maker, uid)
        before = {m: await count(maker, m) for m in (CharacterMemory, UserMemory, Conversation, Message)}

        async with maker() as session:
            real_execute = session.execute
            calls = []

            async def failing_last(statement, *args, **kwargs):
                calls.append(1)
                if len(calls) == 5:  # the conversations delete, after the others ran
                    raise RuntimeError("database went away")
                return await real_execute(statement, *args, **kwargs)

            session.execute = failing_last
            with pytest.raises(RuntimeError):
                await UserDataService(session).delete_all(uid)

        for model, expected in before.items():
            assert await count(maker, model) == expected, model.__name__

    run_db(scenario)


# ----------------------------------------- what users can and cannot do


def test_users_have_no_data_wipe_or_export_command(run_db, tmp_path):
    async def scenario(maker):
        await add_characters(maker, PEOPLE)
        bot = Harness(maker, tmp_path)
        await chat_with(bot)
        uid = await user_id(maker, 1001)
        await seed_state(maker, uid)
        before = await count(maker, Message)

        for command in ("/deletedata", "/export"):
            await bot.send(message_update(command))
            assert bot.texts()[-1] == t("en", "unknown_command"), command
        await bot.send(callback_update("wipeok"))  # an old confirm button from an earlier version

        assert await count(maker, Message) == before and await count(maker, CharacterMemory) > 0
        assert not bot.session.named("SendDocument")

    run_db(scenario)


def test_the_command_menu_does_not_list_them():
    names = {name for name, _ in bot_module._COMMANDS}
    assert "delete" in names  # a user can still delete a chat
    assert not names & {"deletedata", "export"}


def test_deleting_a_chat_never_touches_credits_or_payments(run_db, tmp_path):
    async def scenario(maker):
        await add_characters(maker, PEOPLE)
        bot = Harness(maker, tmp_path)
        await chat_with(bot)
        uid = await user_id(maker, 1001)
        async with maker() as s:
            user = (await s.execute(select(User).where(User.id == uid))).scalar_one()
            user.credits = 77
            conversation = (await s.execute(select(Conversation))).scalars().first()
            s.add(StarPayment(user_id=uid, telegram_charge_id="c1", product="sub", stars=400))
            s.add(
                CreditTransaction(
                    user_id=uid, amount=-1, balance_after=76, reason="message", conversation_id=conversation.id
                )
            )
            await s.commit()

        await bot.send(callback_update(f"{DELETE_CONFIRM_PREFIX}amy"))

        assert await count(maker, Conversation) == 0  # the chat is gone...
        assert await count(maker, StarPayment) == 1  # ...the accounting records are not
        assert await count(maker, CreditTransaction) == 1
        async with maker() as s:
            assert (await s.execute(select(User.credits).where(User.id == uid))).scalar_one() == 77

    run_db(scenario)
