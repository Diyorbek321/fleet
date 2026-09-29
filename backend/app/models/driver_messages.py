"""A message on a driver's phone: from the dispatcher, or from the GPS watcher.

See the ``a1b2c3d4e5f7`` migration for why this is a table rather than a
fire-and-forget push.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class DriverMessageKind(str, enum.Enum):
    """Where a message came from. Stored as text: a new kind is not a migration."""

    dispatcher = "dispatcher"
    gps_silent = "gps_silent"


class DriverMessage(Base):
    __tablename__ = "driver_messages"
    __table_args__ = (
        UniqueConstraint("org_id", "dedupe_key", name="uq_driver_messages_org_key"),
        Index("ix_driver_messages_driver_created", "driver_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    driver_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("drivers.id", ondelete="CASCADE"), nullable=False
    )
    truck_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("trucks.id", ondelete="SET NULL"), nullable=True
    )
    # NULL for the automatic warnings, and for a dispatcher since deleted.
    sent_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    dedupe_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # How many of the driver's devices Expo accepted the push for. Zero means
    # the message is only in the inbox — the panel says so rather than letting
    # the dispatcher believe the phone buzzed.
    devices_delivered: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
