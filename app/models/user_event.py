import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class UserEvent(Base):
    """One thing a user did: a command or a button, by name only.

    No message text, no arguments, no ids of chats or characters. The name is
    one of a closed set (see event_log.py). Deleted by /deletedata.
    """

    __tablename__ = "user_events"
    __table_args__ = (
        Index("ix_user_events_user_created", "user_id", "created_at"),
        Index("ix_user_events_name_created", "name", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
