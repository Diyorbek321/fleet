from __future__ import annotations

import uuid
from datetime import datetime, date, timezone
from sqlalchemy import String, Date, DateTime, Enum, ForeignKey, UniqueConstraint, Numeric, Text, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base
from app.models.enums import ServiceType, ServiceStatus

class ServiceInterval(Base):
    __tablename__ = "service_intervals"
    __table_args__ = (UniqueConstraint("truck_id", "service_type", name="uq_truck_service_type"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    truck_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("trucks.id", ondelete="CASCADE"), nullable=False)
    service_type: Mapped[ServiceType] = mapped_column(Enum(ServiceType, name="service_type"), nullable=False)

    interval_km: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    interval_days: Mapped[int | None] = mapped_column(Integer, nullable=True)

    last_service_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_service_mileage: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    next_service_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    next_service_mileage: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)

    status: Mapped[ServiceStatus] = mapped_column(Enum(ServiceStatus, name="service_status"), default=ServiceStatus.scheduled, nullable=False)

class MaintenanceRecord(Base):
    __tablename__ = "maintenance_records"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    truck_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("trucks.id", ondelete="CASCADE"), nullable=False)
    service_type: Mapped[ServiceType] = mapped_column(Enum(ServiceType, name="service_type"), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    cost: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    mileage_at_service: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    performed_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    performed_at: Mapped[date] = mapped_column(Date, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

class FuelLog(Base):
    __tablename__ = "fuel_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    truck_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("trucks.id", ondelete="CASCADE"), nullable=False)
    trip_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("trips.id", ondelete="SET NULL"), nullable=True)
    liters: Mapped[float] = mapped_column(Numeric(8, 2), nullable=False)
    cost_per_liter: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False)
    total_cost: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    mileage_at_fill: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    fuel_station: Mapped[str | None] = mapped_column(String(200), nullable=True)
    filled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
