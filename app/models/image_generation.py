import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ImageGeneration(Base):
    """One attempt to give a user a picture: the operator's ledger. One row
    per attempt; it is updated, never duplicated.

    Two separate facts:
      * generation (status): "ok", "refused" (moderation) or "failed" for the
        image service call; source says whether it was a real call
        ("provider", which uses Xavira credits) or a stored picture ("cache").
      * delivery (delivery): NULL when no picture was made, otherwise "pending"
        until Telegram answers, then "delivered" or "failed". A picture that was
        paid for but never delivered keeps its provider_credits.
    provider_credits is the provider's own unit (Xavira credits), NOT money; it
    is only filled for successful provider generations (a refused or failed call is
    assumed to use none; check Xavira billing) and when XAVIRA_CREDITS_PER_IMAGE is set. Holds no prompt and no
    chat text. Accounting data, kept like credit transactions.
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
    status: Mapped[str] = mapped_column(String(10), nullable=False)  # generation: "ok", "refused", "failed"
    delivery: Mapped[str | None] = mapped_column(String(10), nullable=True)  # NULL, "pending", "delivered", "failed"
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    model: Mapped[str | None] = mapped_column(String(60), nullable=True)
    provider_credits: Mapped[float | None] = mapped_column(Float, nullable=True)  # Xavira credits, not money
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
