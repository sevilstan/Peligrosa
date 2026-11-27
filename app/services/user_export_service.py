"""Everything we hold about one user, as a JSON file they can keep (/export).

Contains: account basics, their chats with every message, what each character
remembers about them, their own memory records, credit history and payments.
Left out on purpose: the password hash, other users' data, internal model
numbers (mood, relationship scores) and image prompts. Every query is filtered
by user_id, and the character name is the only thing read from other tables.
"""

import json
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.character import Character
from app.models.character_memory import CharacterMemory
from app.models.conversation import Conversation
from app.models.conversation_participant import ConversationParticipant
from app.models.credit_transaction import CreditTransaction
from app.models.message import Message
from app.models.star_payment import StarPayment
from app.models.user import User
from app.models.user_event import UserEvent
from app.models.user_memory import UserMemory


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


class UserExportService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def build(self, user: User) -> bytes:
        data = {
            "exported_at": _iso(datetime.now().astimezone()),
            "account": {
                "name": user.display_name,
                "language": user.language_code,
                "credits": user.credits,
                "subscription_until": _iso(user.subscription_until),
                "created_at": _iso(user.created_at),
            },
            "chats": await self._chats(user),
            "character_memories": await self._character_memories(user),
            "other_memories": await self._user_memories(user),
            "credit_history": await self._credits(user),
            "payments": await self._payments(user),
            "activity_log": await self._events(user),
        }
        return json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")

    async def _chats(self, user: User) -> list[dict]:
        conversations = (
            await self.session.execute(
                select(Conversation).where(Conversation.user_id == user.id).order_by(Conversation.created_at)
            )
        ).scalars().all()
        chats = []
        for conversation in conversations:
            members = (
                await self.session.execute(
                    select(Character.name)
                    .join(ConversationParticipant, ConversationParticipant.character_id == Character.id)
                    .where(ConversationParticipant.conversation_id == conversation.id)
                    .order_by(Character.name)
                )
            ).scalars().all()
            rows = (
                await self.session.execute(
                    select(Message, Character.name)
                    .outerjoin(Character, Character.id == Message.sender_character_id)
                    .where(Message.conversation_id == conversation.id)
                    .order_by(Message.created_at, Message.id)
                )
            ).all()
            chats.append(
                {
                    "title": conversation.title,
                    "type": conversation.conversation_type,
                    "created_at": _iso(conversation.created_at),
                    "characters": list(members),
                    "summary": conversation.summary,
                    "messages": [
                        {
                            "at": _iso(message.created_at),
                            "from": "you" if message.sender_type == "user" else (name or "character"),
                            "type": message.message_type,
                            "text": message.content,
                        }
                        for message, name in rows
                    ],
                }
            )
        return chats

    async def _character_memories(self, user: User) -> list[dict]:
        rows = (
            await self.session.execute(
                select(CharacterMemory, Character.name)
                .join(Character, Character.id == CharacterMemory.character_id)
                .where(CharacterMemory.user_id == user.id)
                .order_by(Character.name, CharacterMemory.created_at)
            )
        ).all()
        return [
            {
                "character": name,
                "category": memory.category,
                "content": memory.content,
                "saved_at": _iso(memory.created_at),
            }
            for memory, name in rows
        ]

    async def _user_memories(self, user: User) -> list[dict]:
        rows = (
            await self.session.execute(
                select(UserMemory).where(UserMemory.user_id == user.id).order_by(UserMemory.created_at)
            )
        ).scalars().all()
        return [
            {"category": m.category, "content": m.content, "saved_at": _iso(m.created_at)} for m in rows
        ]

    async def _credits(self, user: User) -> list[dict]:
        rows = (
            await self.session.execute(
                select(CreditTransaction)
                .where(CreditTransaction.user_id == user.id)
                .order_by(CreditTransaction.created_at)
            )
        ).scalars().all()
        return [
            {"at": _iso(r.created_at), "change": r.amount, "balance": r.balance_after, "reason": r.reason}
            for r in rows
        ]

    async def _payments(self, user: User) -> list[dict]:
        rows = (
            await self.session.execute(
                select(StarPayment).where(StarPayment.user_id == user.id).order_by(StarPayment.created_at)
            )
        ).scalars().all()
        return [
            {
                "at": _iso(r.created_at),
                "product": r.product,
                "stars": r.stars,
                "status": r.status,
                "refunded_at": _iso(r.refunded_at),
            }
            for r in rows
        ]

    async def _events(self, user: User) -> list[dict]:
        rows = (
            await self.session.execute(
                select(UserEvent).where(UserEvent.user_id == user.id).order_by(UserEvent.created_at)
            )
        ).scalars().all()
        return [{"at": _iso(r.created_at), "action": r.name} for r in rows]
