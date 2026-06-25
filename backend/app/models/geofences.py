from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Boolean, DateTime, Numeric, Enum, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import GeofenceEventType


class Geofence(Base):
    """A circular geofence. Enter/exit transitions are detected on GPS ingest.

    Circular (center + radius) keeps evaluation a cheap haversine check with no
    PostGIS dependency — works identically on Postgres and the SQLite test DB.
    """

    __tablename__ = "geofences"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    category: Mapped[str | None] = mapped_column(String(40), nullable=True)  # depot, customer, restricted, ...
    center_lat: Mapped[float] = mapped_column(Numeric(10, 8), nullable=False)
    center_lng: Mapped[float] = mapped_column(Numeric(11, 8), nullable=False)
    radius_m: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)  # meters
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    events: Mapped[list["GeofenceEvent"]] = relationship(back_populates="geofence", cascade="all, delete-orphan")


class GeofenceEvent(Base):
    """A truck crossing the boundary of a geofence (enter or exit)."""

    __tablename__ = "geofence_events"
    __table_args__ = (
        Index("ix_geofence_events_truck_geofence", "truck_id", "geofence_id", "recorded_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    geofence_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("geofences.id", ondelete="CASCADE"), nullable=False)
    truck_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("trucks.id", ondelete="CASCADE"), nullable=False)
    event: Mapped[GeofenceEventType] = mapped_column(Enum(GeofenceEventType, name="geofence_event_type"), nullable=False)
    latitude: Mapped[float] = mapped_column(Numeric(10, 8), nullable=False)
    longitude: Mapped[float] = mapped_column(Numeric(11, 8), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    geofence: Mapped["Geofence"] = relationship(back_populates="events")
