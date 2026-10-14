"""A driver's stays in Russia, for the 90-in-180 count.

One row per stay: the day the driver entered and the day they left (NULL while
still inside). Written automatically when a driver marks "crossed the KZ–RU
border" on a trip — entry on an export, exit on an import — and correctable by
the desk, because the migration card's date is what the border guard reads,
not the app.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import Date, DateTime, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class DriverRussiaStay(Base):
    __tablename__ = "driver_russia_stays"
    __table_args__ = (
        Index("ix_driver_russia_stays_driver", "driver_id", "entered_on"),
        # A driver is in Russia once at a time: at most one stay without an exit.
        Index(
            "uq_driver_russia_stays_open",
            "driver_id",
            unique=True,
            postgresql_where=text("left_on IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    driver_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("drivers.id", ondelete="CASCADE"), nullable=False
    )
    entered_on: Mapped[date] = mapped_column(Date, nullable=False)
    left_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    # "auto" from a border checkpoint, "manual" from the desk.
    source: Mapped[str] = mapped_column(String(10), nullable=False, default="manual")
    # The trip whose checkpoint opened it, when it was automatic.
    trip_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("trips.id", ondelete="SET NULL"), nullable=True
    )
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
