from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.models.enums import TripReportCountry, TripReportExpenseCategory, TripReportStatus


class TripFuelRowIn(BaseModel):
    row_no: int = Field(ge=1)
    kz_liters: Optional[float] = Field(default=None, ge=0)
    kz_amount: Optional[float] = Field(default=None, ge=0)
    rf_liters: Optional[float] = Field(default=None, ge=0)
    rf_amount: Optional[float] = Field(default=None, ge=0)
    doha_liters: Optional[float] = Field(default=None, ge=0)
    doha_amount: Optional[float] = Field(default=None, ge=0)
    e1card_liters: Optional[float] = Field(default=None, ge=0)
    e1card_amount: Optional[float] = Field(default=None, ge=0)


class TripFuelRowOut(TripFuelRowIn):
    class Config:
        from_attributes = True


class TripCountryExpenseLineIn(BaseModel):
    country: TripReportCountry
    category: TripReportExpenseCategory
    amount: float = Field(ge=0)


class TripCountryExpenseLineOut(TripCountryExpenseLineIn):
    class Config:
        from_attributes = True


class TripExpenseReportIn(BaseModel):
    """The full driver-filled form, saved in one call.

    Every field is optional so a driver can save partial progress; ``fuel_rows``
    and ``country_expenses`` fully replace whatever was previously stored.
    """
    plate_number: Optional[str] = Field(default=None, max_length=20)
    driver_name: Optional[str] = Field(default=None, max_length=200)
    report_date: Optional[date] = None
    odometer_out: Optional[float] = Field(default=None, ge=0)
    odometer_in: Optional[float] = Field(default=None, ge=0)
    fuel_at_garage: Optional[float] = Field(default=None, ge=0)
    route_text: Optional[str] = Field(default=None, max_length=255)
    exchange_rate_note: Optional[str] = Field(default=None, max_length=255)

    money_usd: Optional[float] = Field(default=None, ge=0)
    money_rub: Optional[float] = Field(default=None, ge=0)
    money_kzt: Optional[float] = Field(default=None, ge=0)
    money_uzs: Optional[float] = Field(default=None, ge=0)

    usd_to_kzt_given: Optional[float] = Field(default=None, ge=0)
    usd_to_kzt_received: Optional[float] = Field(default=None, ge=0)
    usd_to_rub_given: Optional[float] = Field(default=None, ge=0)
    usd_to_rub_received: Optional[float] = Field(default=None, ge=0)

    border_departure_at: Optional[datetime] = None
    border_arrival_at: Optional[datetime] = None
    electronic_pass_note: Optional[str] = Field(default=None, max_length=255)
    electronic_queue_note: Optional[str] = Field(default=None, max_length=255)

    insurance_rf: Optional[float] = Field(default=None, ge=0)
    insurance_kz: Optional[float] = Field(default=None, ge=0)
    dollar_return: Optional[float] = Field(default=None, ge=0)
    driver_comment: Optional[str] = None

    fuel_rows: list[TripFuelRowIn] = []
    country_expenses: list[TripCountryExpenseLineIn] = []


class FuelColumnTotals(BaseModel):
    liters: float
    amount: float


class TripReportTotals(BaseModel):
    """Auto-calculated subtotals — kept transparent (labelled, not one opaque

    number) so a dispatcher can see exactly what feeds each balance.
    """
    fuel_by_column: dict[str, FuelColumnTotals]
    fuel_liters_total: float
    fuel_amount_total: float
    country_totals: dict[str, float]
    """Per-currency remaining balance: money issued/exchanged-in minus what was
    spent in that currency (fuel + country expenses + insurance), as declared
    so far. Keys: usd, rub, kzt, uzs."""
    currency_balances: dict[str, float]


class TripExpenseReportOut(TripExpenseReportIn):
    id: uuid.UUID
    trip_id: uuid.UUID
    status: TripReportStatus
    submitted_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime
    fuel_rows: list[TripFuelRowOut] = []
    country_expenses: list[TripCountryExpenseLineOut] = []
    totals: TripReportTotals

    class Config:
        from_attributes = True
