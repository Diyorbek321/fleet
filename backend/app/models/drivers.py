from __future__ import annotations

import uuid
from datetime import datetime, date, timezone
from sqlalchemy import String, Date, DateTime, Enum, ForeignKey, UniqueConstraint, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base
from app.models.enums import DriverStatus

class Driver(Base):
    __tablename__ = "drivers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    email: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True)
    license_number: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    license_expiry: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[DriverStatus] = mapped_column(Enum(DriverStatus, name="driver_status"), default=DriverStatus.active, nullable=False)
    photo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    assignments: Mapped[list["DriverAssignment"]] = relationship(back_populates="driver", cascade="all, delete-orphan")
    safety_scores: Mapped[list["SafetyScore"]] = relationship(back_populates="driver", cascade="all, delete-orphan")

class DriverAssignment(Base):
    __tablename__ = "driver_assignments"
    __table_args__ = (UniqueConstraint("truck_id", "unassigned_at", name="uq_active_assignment_per_truck"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    driver_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("drivers.id", ondelete="CASCADE"), nullable=False)
    truck_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("trucks.id", ondelete="CASCADE"), nullable=False)
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    unassigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    driver: Mapped["Driver"] = relationship(back_populates="assignments")

class SafetyScore(Base):
    __tablename__ = "safety_scores"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    driver_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("drivers.id", ondelete="CASCADE"), nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    speeding_events: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    harsh_braking: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    harsh_acceleration: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    idle_time_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    period_start = mapped_column(Date, nullable=False)
    period_end = mapped_column(Date, nullable=False)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    driver: Mapped["Driver"] = relationship(back_populates="safety_scores")
