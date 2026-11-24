import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, SmallInteger, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class CharacterEmotion(Base):
    """A character's current mood towards a user's world (one row each).

    Persists between messages and fades with time (computed when read, see
    CharacterEmotionService); it is NOT reset by a new message.
    """

    __tablename__ = "character_emotions"

    __table_args__ = (
        CheckConstraint("intensity >= 0 AND intensity <= 100", name="ck_character_emotion_intensity"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    character_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("characters.id", ondelete="CASCADE"), primary_key=True
    )

    mood: Mapped[str] = mapped_column(String(30), nullable=False)
    intensity: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
