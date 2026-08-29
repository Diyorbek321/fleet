from __future__ import annotations

import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Integer, DateTime, Numeric, Enum, ForeignKey, UniqueConstraint, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base
from app.models.enums import TruckStatus

class Truck(Base):
    __tablename__ = "trucks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    plate_number: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[TruckStatus] = mapped_column(Enum(TruckStatus, name="truck_status"), default=TruckStatus.offline, nullable=False)
    fuel_level: Mapped[float] = mapped_column(Numeric(5, 2), default=0, nullable=False)   # 0-100
    mileage: Mapped[float] = mapped_column(Numeric(12, 2), default=0, nullable=False)     # km
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    location: Mapped["TruckLocation | None"] = relationship(back_populates="truck", uselist=False, cascade="all, delete-orphan")
    location_history: Mapped[list["TruckLocationHistory"]] = relationship(back_populates="truck", cascade="all, delete-orphan")

class TruckLocation(Base):
    __tablename__ = "truck_locations"
    __table_args__ = (UniqueConstraint("truck_id", name="uq_truck_locations_truck_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    truck_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("trucks.id", ondelete="CASCADE"), nullable=False)
    latitude: Mapped[float] = mapped_column(Numeric(10, 8), nullable=False)
    longitude: Mapped[float] = mapped_column(Numeric(11, 8), nullable=False)
    speed: Mapped[float] = mapped_column(Numeric(6, 2), default=0, nullable=False)
    heading: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    truck: Mapped["Truck"] = relationship(back_populates="location")

class TruckLocationHistory(Base):
    __tablename__ = "truck_location_history"
    # Hot read path: history/report/analytics queries filter by truck and order
    # by time. Without this composite index they full-scan a table that grows
    # unbounded with GPS volume.
    # The retention purge filters on recorded_at alone; the composite index
    # above starts with truck_id and so cannot serve it, leaving the purge to
    # seq-scan the largest table in the database on every run.
    __table_args__ = (
        Index("ix_truck_location_history_truck_recorded", "truck_id", "recorded_at"),
        Index("ix_truck_location_history_recorded_at", "recorded_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    truck_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("trucks.id", ondelete="CASCADE"), nullable=False)
    latitude: Mapped[float] = mapped_column(Numeric(10, 8), nullable=False)
    longitude: Mapped[float] = mapped_column(Numeric(11, 8), nullable=False)
    speed: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    heading: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    truck: Mapped["Truck"] = relationship(back_populates="location_history")
