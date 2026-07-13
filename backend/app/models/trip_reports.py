"""Driver-filled per-trip expense report ("yo'l varaqasi") — the digitized paper form.

One report per trip: header (plate/driver/odometer), money issued in USD/RUB/KZT/UZS
plus currency-exchange rows, a fuel table split by KZ/RF/DOHA/E1CARD, border-crossing
timestamps, and per-country (KZ/RF/UZ) expense line items. Filled by the driver from
the mobile app; the manager views (and prints) it read-only from the web panel.
"""
from __future__ import annotations

import uuid
from datetime import datetime, date, timezone

from sqlalchemy import String, Date, DateTime, Numeric, Enum, ForeignKey, Text, Integer, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import TripReportStatus, TripReportCountry, TripReportExpenseCategory


class TripExpenseReport(Base):
    __tablename__ = "trip_expense_reports"
    __table_args__ = (Index("ix_trip_expense_reports_trip", "trip_id", unique=True),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    trip_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("trips.id", ondelete="CASCADE"), nullable=False
    )

    # Header — plate/driver default from the trip's truck/driver at read time,
    # but are kept editable here since the paper form can name a substitute driver.
    plate_number: Mapped[str | None] = mapped_column(String(20), nullable=True)
    driver_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    report_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    odometer_out: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    odometer_in: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    fuel_at_garage: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    route_text: Mapped[str | None] = mapped_column(String(255), nullable=True)
    exchange_rate_note: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Money issued for the trip ("Деньги на дорогу из гаража")
    money_usd: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    money_rub: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    money_kzt: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    money_uzs: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)

    # Currency exchanged en route
    usd_to_kzt_given: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    usd_to_kzt_received: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    usd_to_rub_given: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    usd_to_rub_received: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)

    # Border crossing ("Проход границы (толчак)")
    border_departure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    border_arrival_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    electronic_pass_note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    electronic_queue_note: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Footer
    insurance_rf: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    insurance_kz: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    dollar_return: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    driver_comment: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[TripReportStatus] = mapped_column(
        Enum(TripReportStatus, name="trip_report_status"), default=TripReportStatus.draft, nullable=False
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    fuel_rows: Mapped[list["TripFuelRow"]] = relationship(
        back_populates="report", cascade="all, delete-orphan", order_by="TripFuelRow.row_no"
    )
    country_expenses: Mapped[list["TripCountryExpenseLine"]] = relationship(
        back_populates="report", cascade="all, delete-orphan"
    )


class TripFuelRow(Base):
    """One numbered row of the GSM (fuel) table, split by KZ/RF/DOHA/E1CARD columns."""

    __tablename__ = "trip_fuel_rows"
    __table_args__ = (Index("ix_trip_fuel_rows_report", "report_id", "row_no"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    report_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("trip_expense_reports.id", ondelete="CASCADE"), nullable=False
    )
    row_no: Mapped[int] = mapped_column(Integer, nullable=False)

    kz_liters: Mapped[float | None] = mapped_column(Numeric(8, 2), nullable=True)
    kz_amount: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    rf_liters: Mapped[float | None] = mapped_column(Numeric(8, 2), nullable=True)
    rf_amount: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    doha_liters: Mapped[float | None] = mapped_column(Numeric(8, 2), nullable=True)
    doha_amount: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    e1card_liters: Mapped[float | None] = mapped_column(Numeric(8, 2), nullable=True)
    e1card_amount: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)

    report: Mapped["TripExpenseReport"] = relationship(back_populates="fuel_rows")


class TripCountryExpenseLine(Base):
    """A single expense cell in one of the KZ/RF/UZ tables (e.g. KZ + Платон = amount)."""

    __tablename__ = "trip_country_expense_lines"
    __table_args__ = (
        UniqueConstraint("report_id", "country", "category", name="uq_trip_country_expense_cell"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    report_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("trip_expense_reports.id", ondelete="CASCADE"), nullable=False
    )
    country: Mapped[TripReportCountry] = mapped_column(Enum(TripReportCountry, name="trip_report_country"), nullable=False)
    category: Mapped[TripReportExpenseCategory] = mapped_column(
        Enum(TripReportExpenseCategory, name="trip_report_expense_category"), nullable=False
    )
    amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)

    report: Mapped["TripExpenseReport"] = relationship(back_populates="country_expenses")
