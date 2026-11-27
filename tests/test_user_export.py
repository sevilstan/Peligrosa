"""/export: a user's own data as a file, and nobody else's."""

import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models import (
    Character,
    CharacterMemory,
    Conversation,
    CreditTransaction,
    Message,
    StarPayment,
    User,
    UserMemory,
)
from app.services.user_export_service import UserExportService
from tests.telegram_harness import Harness, add_characters, callback_update, message_update

WHEN = datetime(2026, 5, 1, 10, 0, tzinfo=timezone.utc)


async def fill(maker, telegram_id, secret):
    """A user with a chat, memories, credits and a payment that all hold `secret`."""
    async with maker() as s:
        user = (await s.execute(select(User).where(User.telegram_id == telegram_id))).scalar_one()
        conv = (await s.execute(select(Conversation).where(Conversation.user_id == user.id))).scalars().first()
        char = (await s.execute(select(Character).where(Character.slug == "amy"))).scalar_one()
        user.display_name = f"name-{secret}"
        s.add_all(
            [
                Message(conversation_id=conv.id, sender_type="user", sender_user_id=user.id,
                        content=f"I said {secret}", message_type="text", created_at=WHEN),
                Message(conversation_id=conv.id, sender_type="character", sender_character_id=char.id,
                        content=f"she said {secret}", message_type="text", created_at=WHEN + timedelta(minutes=1)),
                CharacterMemory(user_id=user.id, character_id=char.id, category="interest",
                                content=f"likes {secret}", importance=3, confidence=0.9),
                UserMemory(user_id=user.id, category="goal", content=f"wants {secret}", importance=3, confidence=0.9),
                CreditTransaction(user_id=user.id, amount=-1, balance_after=9, reason="message"),
                StarPayment(user_id=user.id, telegram_charge_id=f"ch-{secret}", product="pack", stars=50,
                            credits_granted=100, status="paid"),
            ]
        )
        await s.commit()
        return user.id


async def two_users(maker, tmp_path):
    await add_characters(maker, [("Amy", "amy", 0, True)])
    bot = Harness(maker, tmp_path)
    await bot.send(callback_update("open:amy", user_id=1001))
    await bot.send(callback_update("open:amy", user_id=2002, first="Bo"))
    await fill(maker, 1001, "alpha")
    await fill(maker, 2002, "bravo")
    return bot


def test_export_has_the_users_own_data(run_db, tmp_path):
    async def scenario(maker):
        await two_users(maker, tmp_path)
        async with maker() as s:
            user = (await s.execute(select(User).where(User.telegram_id == 1001))).scalar_one()
            data = json.loads(await UserExportService(s).build(user))

        assert data["account"]["name"] == "name-alpha"
        messages = data["chats"][0]["messages"]
        assert [(m["from"], m["text"]) for m in messages] == [("you", "I said alpha"), ("Amy", "she said alpha")]
        assert data["chats"][0]["characters"] == ["Amy"]
        assert data["character_memories"] == [
            {"character": "Amy", "category": "interest", "content": "likes alpha", "saved_at": data["character_memories"][0]["saved_at"]}
        ]
        assert [m["content"] for m in data["other_memories"]] == ["wants alpha"]
        assert data["credit_history"][0]["change"] == -1
        assert data["payments"][0]["stars"] == 50 and "charge" not in json.dumps(data["payments"])

    run_db(scenario)


def test_export_never_holds_another_users_data(run_db, tmp_path):
    async def scenario(maker):
        await two_users(maker, tmp_path)
        async with maker() as s:
            user = (await s.execute(select(User).where(User.telegram_id == 1001))).scalar_one()
            text = (await UserExportService(s).build(user)).decode()
        assert "alpha" in text and "bravo" not in text
        assert "password" not in text

    run_db(scenario)


def test_the_command_sends_a_json_file(run_db, tmp_path):
    async def scenario(maker):
        bot = await two_users(maker, tmp_path)
        await bot.send(message_update("/export", user_id=1001))
        sent = bot.session.named("SendDocument")
        assert len(sent) == 1
        document = sent[0]["document"]
        assert document.filename == "my-peligrosa-data.json"
        body = json.loads(document.data)
        assert "alpha" in json.dumps(body) and "bravo" not in json.dumps(body)

    run_db(scenario)


def test_export_after_deleting_data_has_no_chats(run_db, tmp_path):
    async def scenario(maker):
        from app.services.user_data_service import UserDataService

        await two_users(maker, tmp_path)
        async with maker() as s:
            user = (await s.execute(select(User).where(User.telegram_id == 1001))).scalar_one()
            await UserDataService(s).delete_all(user.id)
            await s.refresh(user)
            data = json.loads(await UserExportService(s).build(user))
        assert data["chats"] == [] and data["character_memories"] == [] and data["other_memories"] == []
        assert data["payments"]  # payment records are kept, so they stay visible to their owner

    run_db(scenario)
