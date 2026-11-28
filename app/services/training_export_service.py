"""Build a training dataset from chats, without anyone who deleted their data.

- Only active users whose data has NOT been wiped by an operator are included.
- Users are pseudonymized (HMAC of the internal id with a private salt): no
  Telegram id, name or username is ever exported. Chat text itself can still
  contain personal details, so treat exports as personal data.
- deleted_pseudonyms() lists the pseudonyms of everyone who deleted their data,
  to purge them from exports made earlier.
"""

import hashlib
import hmac
from typing import AsyncIterator

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.character import Character
from app.models.conversation import Conversation
from app.models.message import Message
from app.models.user import User

MIN_SALT_LENGTH = 16


def pseudonym(salt: str, value) -> str:
    if len(salt or "") < MIN_SALT_LENGTH:
        raise ValueError(f"The export salt must be at least {MIN_SALT_LENGTH} characters.")
    return hmac.new(salt.encode(), str(value).encode(), hashlib.sha256).hexdigest()[:16]


class TrainingExportService:
    def __init__(self, session: AsyncSession, salt: str):
        pseudonym(salt, "check")  # fail early on a missing/short salt
        self.session = session
        self.salt = salt

    async def conversations(self) -> AsyncIterator[dict]:
        users = (
            await self.session.execute(
                select(User.id).where(User.is_active.is_(True), User.data_deleted_at.is_(None))
            )
        ).scalars().all()
        slugs = dict((await self.session.execute(select(Character.id, Character.slug))).all())

        for user_id in users:
            conversations = (
                await self.session.execute(
                    select(Conversation)
                    .where(Conversation.user_id == user_id)
                    .order_by(Conversation.created_at)
                )
            ).scalars().all()

            for conversation in conversations:
                rows = (
                    await self.session.execute(
                        select(Message)
                        .where(
                            Message.conversation_id == conversation.id,
                            Message.message_type != "image",  # a picture has no words to learn from
                        )
                        .order_by(Message.created_at, Message.id)
                    )
                ).scalars().all()
                if not rows:
                    continue

                yield {
                    "user": pseudonym(self.salt, user_id),
                    "conversation": pseudonym(self.salt, conversation.id),
                    "type": conversation.conversation_type,
                    "messages": [
                        {
                            "role": "user" if m.sender_type == "user" else "character",
                            "character": slugs.get(m.sender_character_id),
                            "content": m.content,
                        }
                        for m in rows
                    ],
                }

    async def deleted_pseudonyms(self) -> list[str]:
        ids = (
            await self.session.execute(select(User.id).where(User.data_deleted_at.is_not(None)))
        ).scalars().all()
        return sorted(pseudonym(self.salt, i) for i in ids)
