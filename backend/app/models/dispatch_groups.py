"""The dispatchers' Telegram group, where the fleet board lands each morning.

One per organization. Bound the way a truck's group is — a one-time token in a
``startgroup`` link — so the panel never sees or accepts a chat id.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import Date, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class DispatchTelegramGroup(Base):
    __tablename__ = "dispatch_telegram_groups"
    __table_args__ = (
        UniqueConstraint("org_id", name="uq_dispatch_telegram_groups_org"),
        UniqueConstraint("token", name="uq_dispatch_telegram_groups_token"),
        # The webhook's lookup: removals and supergroup migrations carry only
        # the chat id.
        Index("ix_dispatch_telegram_groups_chat", "chat_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    token: Mapped[str] = mapped_column(String(48), nullable=False)
    # NULL while the link is unused, and again after the bot is removed.
    # Never serialised to the panel.
    chat_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    chat_title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # The Tashkent day the morning board last went out. A date, not a log row:
    # the scheduler ticks every fifteen minutes, and this is what makes the
    # morning copy go once.
    board_sent_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
