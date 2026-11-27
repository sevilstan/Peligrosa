"""The pictures a user has received, newest first (for the /gallery slider).

Scope is strictly the user's own conversations (joined on Conversation.user_id),
so one user can never see another user's pictures.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.character import Character
from app.models.conversation import Conversation
from app.models.message import Message

MAX_PICTURES = 200


@dataclass(frozen=True)
class UserPicture:
    key: str
    character_name: str
    created_at: datetime


class PictureGalleryService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_for_user(self, user_id: uuid.UUID, limit: int = MAX_PICTURES) -> list[UserPicture]:
        result = await self.session.execute(
            select(Message.image_key, Character.name, Message.created_at)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .join(Character, Character.id == Message.sender_character_id)
            .where(
                Conversation.user_id == user_id,
                Message.message_type == "image",
                Message.image_key.is_not(None),
            )
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(limit)
        )
        return [UserPicture(key, name, created) for key, name, created in result.all()]
