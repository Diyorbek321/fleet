"""Models backing the driver mobile app: shifts, driver-reported issues, push tokens."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from datetime import date

from sqlalchemy import String, Date, DateTime, Enum, ForeignKey, Text, Numeric, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.enums import ShiftStatus, MaintenanceRequestStatus, ExpenseCategory


class Shift(Base):
    """A driver's clock-in / clock-out session on a truck."""

    __tablename__ = "shifts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    driver_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("drivers.id", ondelete="CASCADE"), nullable=False, index=True)
    truck_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("trucks.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[ShiftStatus] = mapped_column(Enum(ShiftStatus, name="shift_status"), default=ShiftStatus.active, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    start_mileage: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    end_mileage: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)


class MaintenanceRequest(Base):
    """An issue/maintenance request raised by a driver from the mobile app."""

    __tablename__ = "maintenance_requests"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    driver_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("drivers.id", ondelete="SET NULL"), nullable=True)
    truck_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("trucks.id", ondelete="SET NULL"), nullable=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    photo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[MaintenanceRequestStatus] = mapped_column(
        Enum(MaintenanceRequestStatus, name="maintenance_request_status"),
        default=MaintenanceRequestStatus.open,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class DriverExpense(Base):
    """A daily expense logged by a driver from the mobile app.

    Anchored to the *driver* (not the truck) so dispatchers can rank who spends
    more vs. less. Fuel is tracked separately via ``FuelLog``.
    """

    __tablename__ = "driver_expenses"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    driver_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("drivers.id", ondelete="CASCADE"), nullable=False, index=True)
    truck_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("trucks.id", ondelete="SET NULL"), nullable=True)
    trip_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("trips.id", ondelete="SET NULL"), nullable=True)
    category: Mapped[ExpenseCategory] = mapped_column(Enum(ExpenseCategory, name="expense_category"), default=ExpenseCategory.other, nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    receipt_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    spent_at: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class QueueWatch(Base):
    """A driver's standing request to track their CarGoRuqsat border-queue booking.

    We cannot create the booking (it requires the driver's ЭЦП + SMS/biometric MFA),
    but we can watch the PUBLIC registry by truck plate and notify the driver when
    their booking status changes.
    """

    __tablename__ = "queue_watches"
    __table_args__ = (UniqueConstraint("driver_id", "country", name="uq_queue_watch_driver_country"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    driver_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("drivers.id", ondelete="CASCADE"), nullable=False, index=True)
    plate: Mapped[str] = mapped_column(String(20), nullable=False)
    checkpoint: Mapped[str] = mapped_column(String(200), nullable=False)
    country: Mapped[str | None] = mapped_column(String(100), nullable=True)
    active: Mapped[bool] = mapped_column(default=True, nullable=False)
    last_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    last_notified_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    last_seen_queue_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class PushToken(Base):
    """A registered push notification token for a user's device (FCM/APNs/Expo)."""

    __tablename__ = "push_tokens"
    __table_args__ = (UniqueConstraint("token", name="uq_push_tokens_token"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token: Mapped[str] = mapped_column(String(512), nullable=False)
    platform: Mapped[str | None] = mapped_column(String(20), nullable=True)  # ios | android | expo
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
