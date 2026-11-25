import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class StarPayment(Base):
    """One Telegram Stars payment. The Telegram charge id is unique, so a
    payment notification that arrives twice can only ever be applied once."""

    __tablename__ = "star_payments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    telegram_charge_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    product: Mapped[str] = mapped_column(String(40), nullable=False)
    stars: Mapped[int] = mapped_column(Integer, nullable=False)
    credits_granted: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    days_granted: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # "paid", "refunded" or "needs_review" (paid for something no longer on sale)
    status: Mapped[str] = mapped_column(String(20), default="paid", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    refunded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
