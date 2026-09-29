"""The Telegram group a truck's new orders are posted to.

See the ``c3d4e5f6a7b9`` migration for the binding flow.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class TruckTelegramGroup(Base):
    __tablename__ = "truck_telegram_groups"
    __table_args__ = (
        UniqueConstraint("truck_id", name="uq_truck_telegram_groups_truck"),
        UniqueConstraint("token", name="uq_truck_telegram_groups_token"),
        # The webhook's lookup: removals and supergroup migrations carry only
        # the chat id.
        Index("ix_truck_telegram_groups_chat", "chat_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    truck_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("trucks.id", ondelete="CASCADE"), nullable=False
    )
    # One-time secret in the startgroup link. Never shown again once used.
    token: Mapped[str] = mapped_column(String(48), nullable=False)
    # Filled by the webhook when the bot is added with the link. NULL while
    # the link is unused, and again after the bot is removed from the group.
    # Never serialised to the panel.
    chat_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # The group's name, so the panel can say which group is linked.
    chat_title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
