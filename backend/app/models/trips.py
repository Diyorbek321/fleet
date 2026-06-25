"""Trips / freight orders — the revenue-bearing unit of work.

A trip ties a truck + driver to a load moving from shipper to consignee, with a
rate (revenue) and a status timeline. Fuel logs, driver expenses and maintenance
are reconciled against the trip so the dashboard can show profit-per-trip and
surface leakage (fuel waste, unauthorized stops, idle cost).

Money is stored in UZS by default (the Uzbek market is cash-and-UZS); a currency
code is kept per trip for cross-border loads priced in USD/RUB.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime, Numeric, Enum, ForeignKey, Text, Index, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import TripStatus, TripEventType, SegmentKind


class Trip(Base):
    __tablename__ = "trips"
    __table_args__ = (
        Index("ix_trips_status", "status"),
        Index("ix_trips_truck", "truck_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    reference: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)

    truck_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("trucks.id", ondelete="SET NULL"), nullable=True)
    driver_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("drivers.id", ondelete="SET NULL"), nullable=True)

    status: Mapped[TripStatus] = mapped_column(Enum(TripStatus, name="trip_status"), default=TripStatus.draft, nullable=False)

    # Parties
    shipper: Mapped[str | None] = mapped_column(String(200), nullable=True)
    consignee: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Route
    origin_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    origin_lat: Mapped[float | None] = mapped_column(Numeric(10, 8), nullable=True)
    origin_lng: Mapped[float | None] = mapped_column(Numeric(11, 8), nullable=True)
    destination_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    destination_lat: Mapped[float | None] = mapped_column(Numeric(10, 8), nullable=True)
    destination_lng: Mapped[float | None] = mapped_column(Numeric(11, 8), nullable=True)

    # Cargo
    cargo_description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    cargo_weight_kg: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    is_reefer: Mapped[bool] = mapped_column(default=False, nullable=False)

    # Commercials
    rate: Mapped[float] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="UZS", nullable=False)
    planned_distance_km: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)

    # Schedule / actuals
    scheduled_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scheduled_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    events: Mapped[list["TripEvent"]] = relationship(back_populates="trip", cascade="all, delete-orphan", order_by="TripEvent.recorded_at")
    segments: Mapped[list["TripSegment"]] = relationship(back_populates="trip", cascade="all, delete-orphan", order_by="TripSegment.seq")


class TripEvent(Base):
    """A milestone in a trip's timeline (status change, border arrival, POD, note)."""

    __tablename__ = "trip_events"
    __table_args__ = (Index("ix_trip_events_trip", "trip_id", "recorded_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    trip_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("trips.id", ondelete="CASCADE"), nullable=False)
    event: Mapped[TripEventType] = mapped_column(Enum(TripEventType, name="trip_event_type"), nullable=False)
    from_status: Mapped[TripStatus | None] = mapped_column(Enum(TripStatus, name="trip_status"), nullable=True)
    to_status: Mapped[TripStatus | None] = mapped_column(Enum(TripStatus, name="trip_status"), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    latitude: Mapped[float | None] = mapped_column(Numeric(10, 8), nullable=True)
    longitude: Mapped[float | None] = mapped_column(Numeric(11, 8), nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    trip: Mapped["Trip"] = relationship(back_populates="events")


class TripSegment(Base):
    """A contiguous stretch of a trip classified as moving or stopped.

    Computed by replaying the truck's GPS history between the trip's start and
    delivery and grouping consecutive points by motion. Lets the owner see where
    a truck actually stopped (and for how long) versus where it was driving —
    the raw input for unauthorized-stop / dwell-cost leakage analysis.
    """

    __tablename__ = "trip_segments"
    __table_args__ = (Index("ix_trip_segments_trip", "trip_id", "seq"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    trip_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("trips.id", ondelete="CASCADE"), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[SegmentKind] = mapped_column(Enum(SegmentKind, name="segment_kind"), nullable=False)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    duration_s: Mapped[int] = mapped_column(Integer, nullable=False)

    start_lat: Mapped[float | None] = mapped_column(Numeric(10, 8), nullable=True)
    start_lng: Mapped[float | None] = mapped_column(Numeric(11, 8), nullable=True)
    end_lat: Mapped[float | None] = mapped_column(Numeric(10, 8), nullable=True)
    end_lng: Mapped[float | None] = mapped_column(Numeric(11, 8), nullable=True)

    distance_km: Mapped[float] = mapped_column(Numeric(10, 3), default=0, nullable=False)
    point_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    trip: Mapped["Trip"] = relationship(back_populates="segments")
