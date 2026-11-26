"""Delete everything a user said and everything the characters remember.

What goes: all conversations (with their messages and participants), the
characters' memories of the user, the user's own memory records, relationship
and mood data that belong to the user's chats.

What stays, on purpose: the account row (Telegram id, credit balance,
subscription end) and the credit/payment records. Payment records may have to
be kept by law, and keeping the row stops a deleted account from claiming a
fresh free trial again. The user is told this before confirming.

Everything is filtered by user_id, so no other user's data can be touched; it
all happens in one transaction.
"""

from dataclasses import dataclass

import re
import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.character_emotion import CharacterEmotion
from app.models.character_memory import CharacterMemory
from app.models.character_relationship import CharacterRelationship
from app.models.conversation import Conversation
from app.models.user import User
from app.models.user_memory import UserMemory


_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


def extract_user_ids(text: str) -> list[uuid.UUID]:
    """User ids from a file or from log lines ("... user_id=<uuid> ..."),
    without duplicates, in order."""
    found: list[uuid.UUID] = []
    for match in _UUID.findall(text or ""):
        value = uuid.UUID(match)
        if value not in found:
            found.append(value)
    return found


@dataclass(frozen=True)
class DeletionResult:
    conversations: int
    memories: int


class UserDataService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def delete_all(self, user_id) -> DeletionResult:
        try:
            character_memories = await self.session.execute(
                delete(CharacterMemory).where(CharacterMemory.user_id == user_id)
            )
            user_memories = await self.session.execute(
                delete(UserMemory).where(UserMemory.user_id == user_id)
            )
            await self.session.execute(
                delete(CharacterRelationship).where(CharacterRelationship.user_id == user_id)
            )
            await self.session.execute(
                delete(CharacterEmotion).where(CharacterEmotion.user_id == user_id)
            )
            # Messages and participants go with their conversations (cascade).
            conversations = await self.session.execute(
                delete(Conversation).where(Conversation.user_id == user_id)
            )
            # Remember that this user deleted their data: training exports skip
            # them and old exports/backups can be purged from this list.
            await self.session.execute(
                update(User).where(User.id == user_id).values(data_deleted_at=datetime.now(timezone.utc), display_name=None, name_status="unasked")
            )
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise

        return DeletionResult(
            conversations=conversations.rowcount or 0,
            memories=(character_memories.rowcount or 0) + (user_memories.rowcount or 0),
        )
