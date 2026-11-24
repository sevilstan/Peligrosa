import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, SmallInteger, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

DIMENSIONS = ("trust", "affection", "respect", "jealousy", "rivalry", "familiarity", "tension")


def _value(default: int):
    return mapped_column(SmallInteger, nullable=False, default=default, server_default=str(default))


class CharacterRelationship(Base):
    """How ONE character feels about ANOTHER, within one user's world.

    Directional: Elena->Natalie and Natalie->Elena are separate rows, so they
    can differ (CLAUDE.md section 8). Values are 0..100 and only shape how the
    character behaves; they are never shown to the user.
    """

    __tablename__ = "character_relationships"

    __table_args__ = (
        CheckConstraint("character_id <> other_character_id", name="ck_character_relationship_not_self"),
        *(
            CheckConstraint(f"{name} >= 0 AND {name} <= 100", name=f"ck_character_relationship_{name}")
            for name in DIMENSIONS
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    character_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("characters.id", ondelete="CASCADE"), primary_key=True
    )
    other_character_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("characters.id", ondelete="CASCADE"), primary_key=True
    )

    trust: Mapped[int] = _value(50)
    affection: Mapped[int] = _value(50)
    respect: Mapped[int] = _value(50)
    jealousy: Mapped[int] = _value(0)
    rivalry: Mapped[int] = _value(0)
    familiarity: Mapped[int] = _value(0)
    tension: Mapped[int] = _value(0)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
