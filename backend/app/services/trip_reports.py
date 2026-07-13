"""Trip expense report ("yo'l varaqasi") totals + upsert.

Mirrors the paper form's own math: subtotal each fuel column, subtotal each
country's expense table, and reconcile cash issued/exchanged against cash
spent per currency. Kept as small, labelled subtotals (not one collapsed
number) so a dispatcher can see exactly what feeds each balance — the exact
reconciliation rules may need adjusting once real reports are compared
against what dispatchers expect.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.enums import TripReportCountry
from app.models.trip_reports import TripCountryExpenseLine, TripExpenseReport, TripFuelRow
from app.schemas.trip_reports import (
    FuelColumnTotals,
    TripCountryExpenseLineOut,
    TripExpenseReportIn,
    TripExpenseReportOut,
    TripFuelRowOut,
    TripReportTotals,
)

_FUEL_COLUMNS = ("kz", "rf", "doha", "e1card")


def _num(v) -> float:
    return float(v) if v is not None else 0.0


def compute_report_totals(
    report: TripExpenseReport | None,
    fuel_rows: list[TripFuelRow],
    country_lines: list[TripCountryExpenseLine],
) -> TripReportTotals:
    fuel_by_column: dict[str, FuelColumnTotals] = {}
    for col in _FUEL_COLUMNS:
        liters = sum(_num(getattr(row, f"{col}_liters")) for row in fuel_rows)
        amount = sum(_num(getattr(row, f"{col}_amount")) for row in fuel_rows)
        fuel_by_column[col] = FuelColumnTotals(liters=round(liters, 2), amount=round(amount, 2))

    fuel_liters_total = round(sum(c.liters for c in fuel_by_column.values()), 2)
    fuel_amount_total = round(sum(c.amount for c in fuel_by_column.values()), 2)

    country_totals: dict[str, float] = {c.value: 0.0 for c in TripReportCountry}
    for line in country_lines:
        country_totals[line.country.value] = round(country_totals[line.country.value] + _num(line.amount), 2)

    money_usd = _num(report.money_usd) if report else 0.0
    money_rub = _num(report.money_rub) if report else 0.0
    money_kzt = _num(report.money_kzt) if report else 0.0
    money_uzs = _num(report.money_uzs) if report else 0.0
    usd_to_kzt_given = _num(report.usd_to_kzt_given) if report else 0.0
    usd_to_kzt_received = _num(report.usd_to_kzt_received) if report else 0.0
    usd_to_rub_given = _num(report.usd_to_rub_given) if report else 0.0
    usd_to_rub_received = _num(report.usd_to_rub_received) if report else 0.0
    insurance_rf = _num(report.insurance_rf) if report else 0.0
    insurance_kz = _num(report.insurance_kz) if report else 0.0
    dollar_return = _num(report.dollar_return) if report else 0.0

    # DOHA/E1CARD fuel columns are card-based fuel systems, not cash held in a
    # currency, so they aren't netted against a cash balance below.
    currency_balances = {
        "usd": round(money_usd - usd_to_kzt_given - usd_to_rub_given - dollar_return, 2),
        "rub": round(
            money_rub + usd_to_rub_received - fuel_by_column["rf"].amount
            - country_totals[TripReportCountry.ru.value] - insurance_rf,
            2,
        ),
        "kzt": round(
            money_kzt + usd_to_kzt_received - fuel_by_column["kz"].amount
            - country_totals[TripReportCountry.kz.value] - insurance_kz,
            2,
        ),
        "uzs": round(money_uzs - country_totals[TripReportCountry.uz.value], 2),
    }

    return TripReportTotals(
        fuel_by_column=fuel_by_column,
        fuel_liters_total=fuel_liters_total,
        fuel_amount_total=fuel_amount_total,
        country_totals=country_totals,
        currency_balances=currency_balances,
    )


_HEADER_FIELDS = [
    f for f in TripExpenseReportIn.model_fields if f not in ("fuel_rows", "country_expenses")
]


def build_report_out(report: TripExpenseReport) -> TripExpenseReportOut:
    """Serialize a report + its freshly computed totals into the API shape."""
    totals = compute_report_totals(report, report.fuel_rows, report.country_expenses)
    return TripExpenseReportOut(
        id=report.id,
        trip_id=report.trip_id,
        status=report.status,
        submitted_at=report.submitted_at,
        created_at=report.created_at,
        updated_at=report.updated_at,
        fuel_rows=[TripFuelRowOut.model_validate(r) for r in report.fuel_rows],
        country_expenses=[TripCountryExpenseLineOut.model_validate(l) for l in report.country_expenses],
        totals=totals,
        **{f: getattr(report, f) for f in _HEADER_FIELDS},
    )


async def get_report(db: AsyncSession, trip_id: uuid.UUID) -> TripExpenseReport | None:
    """Fetch a trip's report with its fuel rows / country expenses eagerly loaded.

    Eager loading matters here beyond the usual N+1 concern: under the async
    ORM, touching an unloaded relationship outside of an ``await`` raises
    ``MissingGreenlet`` — every caller that reads or reassigns these
    collections (``build_report_out``, ``upsert_report``) needs them already
    in memory.
    """
    res = await db.execute(
        select(TripExpenseReport)
        .where(TripExpenseReport.trip_id == trip_id)
        .options(selectinload(TripExpenseReport.fuel_rows), selectinload(TripExpenseReport.country_expenses))
    )
    return res.scalar_one_or_none()


def _validate_report_lines(data: TripExpenseReportIn) -> None:
    """Reject duplicate rows the DB would otherwise refuse.

    ``trip_country_expense_lines`` has a ``uq_trip_country_expense_cell``
    unique constraint on ``(report_id, country, category)`` — two incoming
    lines for the same country+category pair would otherwise reach the
    DB and blow up as an unhandled ``IntegrityError`` (500) instead of a
    clean, actionable validation error. ``trip_fuel_rows`` has no DB-level
    uniqueness on ``row_no`` (only a non-unique index), but duplicate row
    numbers are still nonsensical for a numbered fuel table, so they're
    rejected here too for consistency.
    """
    seen_cells: set[tuple[str, str]] = set()
    for line in data.country_expenses:
        cell = (line.country.value, line.category.value)
        if cell in seen_cells:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Duplicate expense line for country '{cell[0]}' and category "
                    f"'{cell[1]}' — each country/category combination may only appear once."
                ),
            )
        seen_cells.add(cell)

    seen_row_nos: set[int] = set()
    for row in data.fuel_rows:
        if row.row_no in seen_row_nos:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Duplicate fuel row number '{row.row_no}' — each row_no may only appear once.",
            )
        seen_row_nos.add(row.row_no)


async def upsert_report(
    db: AsyncSession, trip_id: uuid.UUID, org_id: uuid.UUID, data: TripExpenseReportIn
) -> TripExpenseReport:
    """Create or replace a trip's report in one call.

    Fuel rows and country-expense lines are small, fixed-size collections
    scoped to a single driver editing their own report, so the simplest
    correct approach is to replace them wholesale on every save: delete
    whatever rows exist for this report, insert the new set. (Reassigning the
    ORM relationship instead — relying on ``cascade="all, delete-orphan"`` —
    races the replacement INSERTs against the orphan DELETEs within the same
    flush and can trip the ``(report_id, country, category)`` unique
    constraint; explicit delete-then-insert has no such ordering hazard.)
    """
    _validate_report_lines(data)
    existing = await get_report(db, trip_id)
    header = data.model_dump(exclude={"fuel_rows", "country_expenses"})

    if existing is None:
        report = TripExpenseReport(org_id=org_id, trip_id=trip_id, **header)
        db.add(report)
        await db.flush()  # assigns report.id for the child rows below
    else:
        report = existing
        for k, v in header.items():
            setattr(report, k, v)
        report.updated_at = datetime.now(timezone.utc)
        await db.execute(delete(TripFuelRow).where(TripFuelRow.report_id == report.id))
        await db.execute(delete(TripCountryExpenseLine).where(TripCountryExpenseLine.report_id == report.id))

    db.add_all(TripFuelRow(report_id=report.id, **row.model_dump()) for row in data.fuel_rows)
    db.add_all(
        TripCountryExpenseLine(report_id=report.id, **line.model_dump()) for line in data.country_expenses
    )
    await db.commit()

    # `report.fuel_rows`/`country_expenses` may still hold the pre-delete
    # objects in memory: within the same session, `selectinload` skips
    # re-querying a relationship that's already loaded on this identity-mapped
    # object, so a plain re-fetch via get_report() would return stale data.
    # An explicit refresh forces those two attributes to reload from the DB.
    await db.refresh(report, attribute_names=["fuel_rows", "country_expenses"])
    return report
