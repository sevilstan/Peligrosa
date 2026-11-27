import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ImageGeneration(Base):
    """One attempt to give a user a picture: the operator's cost ledger.

    source "provider" = a real image-service call (costs money), "cache" = a
    stored picture was reused. status is "ok", "refused" (moderation) or
    "failed". cost is in the provider's own units (Xavira credits) and is only
    filled when XAVIRA_COST_PER_IMAGE is set. Holds no prompt and no chat text.
    Like credit transactions it is kept after /deletedata (accounting).
    """

    __tablename__ = "image_generations"
    __table_args__ = (Index("ix_image_generations_created", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    character_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("characters.id", ondelete="SET NULL"), nullable=True, index=True
    )
    kind: Mapped[str] = mapped_column(String(10), nullable=False)  # "photo" or "art"
    source: Mapped[str] = mapped_column(String(10), nullable=False)  # "provider" or "cache"
    status: Mapped[str] = mapped_column(String(10), nullable=False)  # "ok", "refused", "failed"
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    model: Mapped[str | None] = mapped_column(String(60), nullable=True)
    cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
