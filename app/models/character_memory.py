import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class CharacterMemory(Base):
    __tablename__ = "character_memories"

    __table_args__ = (
        CheckConstraint(
            "importance >= 1 AND importance <= 10",
            name="ck_character_memory_importance",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_character_memory_confidence",
        ),
        CheckConstraint(
            "source_kind IS NULL OR source_kind IN ('direct', 'group')",
            name="ck_character_memory_source_kind",
        ),
        UniqueConstraint(
            "user_id",
            "character_id",
            "category",
            "content",
            name="uq_character_memory_user_character_category_content",
        ),
        UniqueConstraint(
            "user_id",
            "character_id",
            "memory_key",
            name="uq_character_memory_user_character_key",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    character_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("characters.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    category: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    memory_key: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    importance: Mapped[int] = mapped_column(
        Integer,
        default=5,
        nullable=False,
    )

    confidence: Mapped[float] = mapped_column(
        Float,
        default=0.8,
        nullable=False,
    )

    # Where the character learned this. Memory itself never belongs to a
    # conversation (it is per user + character); this is only provenance, for
    # privacy decisions and debugging. SET NULL: deleting a chat keeps the memory.
    source_conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="SET NULL"),
        nullable=True,
    )

    source_kind: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
