"""Fleet reports. Lightweight aggregations suitable for dashboards and CSVs."""
from datetime import date, datetime, timedelta, timezone
from typing import Optional
import math
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.deps.auth import get_current_user, get_org_id, require_role
from app.models.drivers import Driver
from app.models.driver_app import DriverExpense
from app.models.enums import DriverStatus, TruckStatus, UserRole
from app.models.maintenance import FuelLog, MaintenanceRecord
from app.models.trucks import Truck, TruckLocationHistory
from app.services.ai_reports import (
    LANGUAGE_NAMES,
    ReportLanguage,
    ReportType,
    generate_report,
)
from app.services.country_expense_xlsx import (
    build_workbook as build_country_workbook,
    filename_for as country_filename_for,
)
from app.services.country_expenses import build_country_expense_report, default_range
from app.services.period_report_xlsx import build_workbook, filename_for
from app.services.period_reports import PeriodKind, build_period_report, resolve_period

router = APIRouter(prefix="/api/reports", tags=["Reports"])


class FleetSummary(BaseModel):
    total_trucks: int
    active_drivers: int
    total_maintenance_cost: float
    total_fuel_cost: float
    total_fuel_liters: float
    distance_km: float
    window_start: datetime
    window_end: datetime


class TruckDistance(BaseModel):
    truck_id: str
    truck_name: str
    plate_number: str
    distance_km: float
    point_count: int


class DriverExpenseRank(BaseModel):
    driver_id: str
    driver_name: str
    total: float
    entry_count: int
    by_category: dict[str, float]


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


async def _compute_distances(
    db: AsyncSession, start: datetime, end: datetime, org_id: uuid.UUID
) -> dict[str, tuple[float, int]]:
    """Sum haversine distance per truck across the location-history window (this org)."""
    stmt = (
        select(TruckLocationHistory)
        .join(Truck, Truck.id == TruckLocationHistory.truck_id)
        .where(
            TruckLocationHistory.recorded_at >= start,
            TruckLocationHistory.recorded_at <= end,
            Truck.org_id == org_id,
        )
        .order_by(TruckLocationHistory.truck_id, TruckLocationHistory.recorded_at)
    )
    by_truck: dict[str, tuple[float, int]] = {}
    prev_truck: Optional[str] = None
    prev_lat: Optional[float] = None
    prev_lon: Optional[float] = None
    total_km = 0.0
    count = 0

    for row in (await db.execute(stmt)).scalars():
        tid = str(row.truck_id)
        if tid != prev_truck:
            if prev_truck is not None:
                by_truck[prev_truck] = (total_km, count)
            prev_truck = tid
            prev_lat, prev_lon = float(row.latitude), float(row.longitude)
            total_km = 0.0
            count = 1
            continue
        total_km += _haversine_km(prev_lat, prev_lon, float(row.latitude), float(row.longitude))
        prev_lat, prev_lon = float(row.latitude), float(row.longitude)
        count += 1

    if prev_truck is not None:
        by_truck[prev_truck] = (total_km, count)
    return by_truck


@router.get("/fleet-summary", response_model=FleetSummary)
async def fleet_summary(
    days: int = Query(default=30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    org: uuid.UUID = Depends(get_org_id),
):
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)

    total_trucks = (await db.execute(select(func.count(Truck.id)).where(Truck.org_id == org))).scalar() or 0
    active_drivers = (
        await db.execute(
            select(func.count(Driver.id)).where(Driver.org_id == org, Driver.status == DriverStatus.active)
        )
    ).scalar() or 0

    maint_cost = (
        await db.execute(
            select(func.coalesce(func.sum(MaintenanceRecord.cost), 0))
            .join(Truck, Truck.id == MaintenanceRecord.truck_id)
            .where(MaintenanceRecord.performed_at >= start.date(), Truck.org_id == org)
        )
    ).scalar() or 0
    fuel_cost = (
        await db.execute(
            select(func.coalesce(func.sum(FuelLog.total_cost), 0))
            .join(Truck, Truck.id == FuelLog.truck_id)
            .where(FuelLog.filled_at >= start, Truck.org_id == org)
        )
    ).scalar() or 0
    fuel_liters = (
        await db.execute(
            select(func.coalesce(func.sum(FuelLog.liters), 0))
            .join(Truck, Truck.id == FuelLog.truck_id)
            .where(FuelLog.filled_at >= start, Truck.org_id == org)
        )
    ).scalar() or 0

    distances = await _compute_distances(db, start, end, org)
    total_km = sum(km for km, _ in distances.values())

    return FleetSummary(
        total_trucks=int(total_trucks),
        active_drivers=int(active_drivers),
        total_maintenance_cost=float(maint_cost),
        total_fuel_cost=float(fuel_cost),
        total_fuel_liters=float(fuel_liters),
        distance_km=round(total_km, 2),
        window_start=start,
        window_end=end,
    )


@router.get("/truck-distances", response_model=list[TruckDistance])
async def truck_distances(
    days: int = Query(default=30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    org: uuid.UUID = Depends(get_org_id),
):
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)

    trucks = (await db.execute(select(Truck).where(Truck.org_id == org))).scalars().all()
    distances = await _compute_distances(db, start, end, org)

    out: list[TruckDistance] = []
    for t in trucks:
        km, count = distances.get(str(t.id), (0.0, 0))
        out.append(
            TruckDistance(
                truck_id=str(t.id),
                truck_name=t.name,
                plate_number=t.plate_number,
                distance_km=round(km, 2),
                point_count=count,
            )
        )
    out.sort(key=lambda x: x.distance_km, reverse=True)
    return out


@router.get("/driver-expenses", response_model=list[DriverExpenseRank])
async def driver_expenses(
    days: int = Query(default=30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    org: uuid.UUID = Depends(get_org_id),
    _user=Depends(require_role(UserRole.admin, UserRole.manager, UserRole.operator)),
):
    """Per-driver expense totals over the window, ranked high → low.

    Answers "which driver spends more vs. less". Fuel is reported separately.
    """
    end = datetime.now(timezone.utc)
    start = (end - timedelta(days=days)).date()

    rows = (
        await db.execute(
            select(
                DriverExpense.driver_id,
                Driver.name,
                DriverExpense.category,
                func.coalesce(func.sum(DriverExpense.amount), 0),
                func.count(DriverExpense.id),
            )
            .join(Driver, Driver.id == DriverExpense.driver_id)
            .where(DriverExpense.spent_at >= start, Driver.org_id == org)
            .group_by(DriverExpense.driver_id, Driver.name, DriverExpense.category)
        )
    ).all()

    agg: dict[str, DriverExpenseRank] = {}
    for driver_id, name, category, total, count in rows:
        did = str(driver_id)
        rank = agg.get(did)
        if rank is None:
            rank = DriverExpenseRank(
                driver_id=did, driver_name=name, total=0.0, entry_count=0, by_category={}
            )
            agg[did] = rank
        cat = category.value if hasattr(category, "value") else str(category)
        rank.by_category[cat] = round(float(total), 2)
        rank.total = round(rank.total + float(total), 2)
        rank.entry_count += int(count)

    out = sorted(agg.values(), key=lambda r: r.total, reverse=True)
    return out


_VALID_TYPES = {"fuel", "maintenance", "trucks", "drivers", "full"}


@router.get("/generate")
async def generate_ai_report(
    report_type: str = Query(..., pattern="^(fuel|maintenance|trucks|drivers|full)$"),
    language: str = Query(..., pattern="^(en|ru|uz)$"),
    days: int = Query(default=30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role(UserRole.admin)),
) -> Response:
    if report_type not in _VALID_TYPES or language not in LANGUAGE_NAMES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid parameters")
    try:
        report = await generate_report(
            db,
            report_type=report_type,  # type: ignore[arg-type]
            language=language,  # type: ignore[arg-type]
            days=days,
            org_id=user.org_id,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    except Exception:  # network / upstream AI errors — don't leak upstream detail to the client
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI report generation failed. Please try again later.",
        )
    return Response(
        content=report.content,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{report.filename}"'},
    )


# ── Calendar-period reports ──────────────────────────────────────────────────
#
# Separate from the endpoints above on purpose. Those answer "how are we doing
# lately" over a rolling window, which is right for a dashboard. These produce a
# *document*: a fixed calendar month or week that returns identical numbers to
# whoever opens it, whenever they open it. A rolling window cannot promise that,
# and a report an owner cannot re-derive tomorrow is not one they will send to
# anybody.


class PeriodTruckLine(BaseModel):
    truck_id: str
    name: str
    plate_number: str
    trips: int
    revenue: float
    fuel_cost: float
    fuel_liters: float
    expense_cost: float
    maintenance_cost: float
    total_cost: float
    profit: float
    distance_km: float
    l_per_100km: Optional[float]


class PeriodDriverLine(BaseModel):
    driver_id: str
    name: str
    trips: int
    revenue: float
    expense_cost: float


class PeriodReportOut(BaseModel):
    kind: str
    label: str
    start: date
    end: date
    organization: str
    generated_at: datetime
    currency: str

    trips_delivered: int
    trips_in_progress: int
    revenue: float
    fuel_cost: float
    fuel_liters: float
    expense_cost: float
    maintenance_cost: float
    total_cost: float
    profit: float
    margin_pct: float
    distance_km: float
    l_per_100km: Optional[float]
    # False when too little refuelling happened in the period for the ratio to
    # mean anything — see PeriodReport.consumption_reliable. Clients should say
    # so rather than print a figure someone will act on.
    consumption_reliable: bool
    # True when the period reaches past the GPS retention horizon, so distance
    # — and therefore L/100km — covers only part of it.
    distance_partial: bool

    trucks: list[PeriodTruckLine]
    drivers: list[PeriodDriverLine]


def _to_out(report) -> PeriodReportOut:
    return PeriodReportOut(
        kind=report.period.kind,
        label=report.period.label,
        start=report.period.start,
        end=report.period.end,
        organization=report.organization,
        generated_at=report.generated_at,
        currency=report.currency,
        trips_delivered=report.trips_delivered,
        trips_in_progress=report.trips_in_progress,
        revenue=report.revenue,
        fuel_cost=report.fuel_cost,
        fuel_liters=report.fuel_liters,
        expense_cost=report.expense_cost,
        maintenance_cost=report.maintenance_cost,
        total_cost=report.total_cost,
        profit=report.profit,
        margin_pct=report.margin_pct,
        distance_km=report.distance_km,
        l_per_100km=report.l_per_100km,
        consumption_reliable=report.consumption_reliable,
        distance_partial=report.distance_partial,
        trucks=[
            PeriodTruckLine(
                truck_id=line.truck_id,
                name=line.name,
                plate_number=line.plate_number,
                trips=line.trips,
                revenue=line.revenue,
                fuel_cost=round(line.fuel_cost, 2),
                fuel_liters=round(line.fuel_liters, 1),
                expense_cost=round(line.expense_cost, 2),
                maintenance_cost=round(line.maintenance_cost, 2),
                total_cost=line.total_cost,
                profit=line.profit,
                distance_km=line.distance_km,
                l_per_100km=line.l_per_100km,
            )
            for line in report.trucks
        ],
        drivers=[
            PeriodDriverLine(
                driver_id=d.driver_id,
                name=d.name,
                trips=d.trips,
                revenue=round(d.revenue, 2),
                expense_cost=round(d.expense_cost, 2),
            )
            for d in report.drivers
        ],
    )


# `offset` counts periods back from the current one, rather than taking dates,
# so "last month" is one link the client can render without doing calendar
# arithmetic — and so two clients cannot disagree about where a month begins.
_OFFSET = Query(default=0, ge=0, le=60, description="0 = current period, 1 = the one before")


@router.get("/period", response_model=PeriodReportOut)
async def period_report(
    kind: PeriodKind = Query(..., description="week | month"),
    offset: int = _OFFSET,
    db: AsyncSession = Depends(get_db),
    org: uuid.UUID = Depends(get_org_id),
):
    """One calendar week or month of money and movement, for this organization."""
    report = await build_period_report(db, org, resolve_period(kind, offset))
    return _to_out(report)


@router.get("/period.xlsx")
async def period_report_xlsx(
    kind: PeriodKind = Query(..., description="week | month"),
    offset: int = _OFFSET,
    db: AsyncSession = Depends(get_db),
    org: uuid.UUID = Depends(get_org_id),
) -> Response:
    """The same report as a spreadsheet, for the customer's accountant."""
    report = await build_period_report(db, org, resolve_period(kind, offset))
    return Response(
        content=build_workbook(report),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename_for(report)}"'},
    )


# ── Country expenses: where one truck's money went, per round trip ─────────


class CategoryLineOut(BaseModel):
    category: str
    amount: float
    amount_usd: Optional[float]
    liters: Optional[float]


class CountryBlockOut(BaseModel):
    """One country's share of a trip (or of the whole range), itemised.

    ``amount``/``total`` are in ``currency`` — the money as it was actually
    spent. Only the ``*_usd`` figures may be compared or added across
    countries, and they are ``None`` when no rate was available rather than
    zero: nothing was converted, which is not the same as nothing was spent.
    """
    country: str
    currency: str
    lines: list[CategoryLineOut]
    total: float
    total_usd: Optional[float]
    fuel_liters: float
    rate: Optional[float]
    # trip = the exchange this trip itself recorded, org = the organization's
    # configured rate, mixed = several of the above across the aggregated trips.
    rate_source: Optional[str]


class CardFuelOut(BaseModel):
    column: str
    liters: float
    amount: float


class CountryExpenseTripOut(BaseModel):
    trip_id: str
    reference: str
    truck_id: Optional[str]
    truck_name: Optional[str]
    plate_number: Optional[str]
    driver_name: Optional[str]
    trip_date: Optional[date]
    route: Optional[str]
    distance_km: Optional[float]
    report_status: Optional[str]
    countries: list[CountryBlockOut]
    cards: list[CardFuelOut]
    total_usd: Optional[float]
    usd_partial: bool


class CountryExpenseReportOut(BaseModel):
    organization: str
    start: date
    end: date
    generated_at: datetime
    truck_id: Optional[str]
    trips: list[CountryExpenseTripOut]
    countries: list[CountryBlockOut]
    cards: list[CardFuelOut]
    total_usd: Optional[float]
    usd_partial: bool
    countries_missing_rate: list[str]


def _block_out(block) -> CountryBlockOut:
    return CountryBlockOut(
        country=block.country,
        currency=block.currency,
        lines=[
            CategoryLineOut(
                category=l.category, amount=l.amount, amount_usd=l.amount_usd, liters=l.liters
            )
            for l in block.lines
        ],
        total=block.total,
        total_usd=block.total_usd,
        fuel_liters=block.fuel_liters,
        rate=block.rate,
        rate_source=block.rate_source,
    )


def _country_expenses_out(report) -> CountryExpenseReportOut:
    return CountryExpenseReportOut(
        organization=report.organization,
        start=report.start,
        end=report.end,
        generated_at=report.generated_at,
        truck_id=report.truck_id,
        trips=[
            CountryExpenseTripOut(
                trip_id=t.trip_id,
                reference=t.reference,
                truck_id=t.truck_id,
                truck_name=t.truck_name,
                plate_number=t.plate_number,
                driver_name=t.driver_name,
                trip_date=t.trip_date,
                route=t.route,
                distance_km=t.distance_km,
                report_status=t.report_status,
                countries=[_block_out(b) for b in t.countries],
                cards=[CardFuelOut(column=c.column, liters=c.liters, amount=c.amount) for c in t.cards],
                total_usd=t.total_usd,
                usd_partial=t.usd_partial,
            )
            for t in report.trips
        ],
        countries=[_block_out(b) for b in report.countries],
        cards=[CardFuelOut(column=c.column, liters=c.liters, amount=c.amount) for c in report.cards],
        total_usd=report.total_usd,
        usd_partial=report.usd_partial,
        countries_missing_rate=report.countries_missing_rate,
    )


# Explicit dates rather than a rolling `days=` window: a round trip to Moscow
# and back takes three weeks, so the range a user wants is "August", or "this
# truck since spring" — a window measured from today keeps sliding out from
# under the trip they were looking at.
_FROM = Query(default=None, alias="from", description="First day of the range (local date)")
_TO = Query(default=None, alias="to", description="Last day of the range, inclusive")


def _resolve_range(date_from: Optional[date], date_to: Optional[date]) -> tuple[date, date]:
    start, end = default_range()
    start = date_from or start
    end = date_to or end
    if start > end:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="'from' must not be later than 'to'",
        )
    return start, end


@router.get("/country-expenses", response_model=CountryExpenseReportOut)
async def country_expenses(
    date_from: Optional[date] = _FROM,
    date_to: Optional[date] = _TO,
    truck_id: Optional[uuid.UUID] = Query(default=None, description="Limit to one truck"),
    db: AsyncSession = Depends(get_db),
    org: uuid.UUID = Depends(get_org_id),
):
    """Per-trip spending split by the country it happened in, itemised by what for.

    One row per round trip that has a driver-filled report, each carrying an
    Uzbek, Kazakh and Russian block; plus the same three blocks rolled up over
    the whole range. Pass ``truck_id`` for one lorry's history.
    """
    start, end = _resolve_range(date_from, date_to)
    report = await build_country_expense_report(db, org, start=start, end=end, truck_id=truck_id)
    return _country_expenses_out(report)


@router.get("/country-expenses.xlsx")
async def country_expenses_xlsx(
    date_from: Optional[date] = _FROM,
    date_to: Optional[date] = _TO,
    truck_id: Optional[uuid.UUID] = Query(default=None, description="Limit to one truck"),
    db: AsyncSession = Depends(get_db),
    org: uuid.UUID = Depends(get_org_id),
) -> Response:
    """The same breakdown as a spreadsheet, one sheet per way of reading it."""
    start, end = _resolve_range(date_from, date_to)
    report = await build_country_expense_report(db, org, start=start, end=end, truck_id=truck_id)
    return Response(
        content=build_country_workbook(report),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{country_filename_for(report)}"'},
    )
