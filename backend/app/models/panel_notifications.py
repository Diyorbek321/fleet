"""One owner alert, as the panel's bell shows it.

See the ``b2c3d4e5f6a8`` migration for why this exists beside Telegram.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class PanelNotification(Base):
    __tablename__ = "panel_notifications"
    __table_args__ = (
        UniqueConstraint("org_id", "dedupe_key", name="uq_panel_notifications_org_key"),
        Index("ix_panel_notifications_org_created", "org_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    # Text, like NotificationLog.kind: a new AlertKind must not need a migration.
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    # Plain text. The Telegram body is HTML; the panel renders text, never markup.
    body: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default=text("''"))
    # Panel route the alert is about ("/trips/<id>"), when there is one.
    path: Mapped[str | None] = mapped_column(String(300), nullable=True)
    dedupe_key: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
