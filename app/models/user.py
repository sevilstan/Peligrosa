import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    telegram_id: Mapped[int | None] = mapped_column(
        BigInteger,
        unique=True,
        nullable=True,
    )

    email: Mapped[str | None] = mapped_column(
        String(255),
        unique=True,
        nullable=True,
    )

    password_hash: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    display_name: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    # unasked -> asked -> custom. Only a "custom" name (typed by the user) is
    # kept; Telegram's own name is refreshed on every update until then.
    name_status: Mapped[str] = mapped_column(
        String(10),
        default="unasked",
        server_default="unasked",
    )

    language_code: Mapped[str] = mapped_column(
        String(5),
        default="en",
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
    )

    # Opt-in: characters may write first only if the user turned this on
    # (/proactive). Off by default.
    proactive_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false",
        nullable=False,
    )

    # Credits: every user message spends some; a subscription (until the given
    # time) replaces spending. The trial is granted once, lazily.
    credits: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    subscription_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    trial_granted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Set when the user used /deletedata. Training exports skip these users, and
    # the list of them is used to purge older exports and restored backups.
    data_deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    conversations: Mapped[list["Conversation"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
