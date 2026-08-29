"""Calendar-period reports — the document an owner hands to their accountant.

The Reports screen already answers "how are we doing lately" with a rolling
window: last 7 days, last 30. That is the right shape for a dashboard and the
wrong shape for a document. "Avgust oyi hisoboti" means the 1st to the 31st,
the same range every time anyone re-runs it, and two people opening it on
different days must see identical numbers. A rolling window cannot promise
that.

Which date a row belongs to, and why:

* a trip counts in the period it was **delivered**, because that is when the
  freight was earned. Trips still on the road are reported separately rather
  than dropped, so revenue in flight is visible instead of missing;
* fuel by ``filled_at``, driver expenses by ``spent_at``, maintenance by
  ``performed_at`` — all of them the day the money left.

Boundaries are local (Asia/Tashkent by default), not UTC. A month that starts
at 00:00 UTC starts at 05:00 on the 1st in Tashkent, which puts the first five
hours of business into the previous month's report.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.driver_app import DriverExpense
from app.models.drivers import Driver
from app.models.enums import TripStatus
from app.models.maintenance import FuelLog, MaintenanceRecord
from app.models.organizations import Organization
from app.models.trips import Trip
from app.models.trucks import Truck, TruckLocationHistory
from app.services.analytics import _haversine_km

PeriodKind = Literal["week", "month"]

# Uzbek month names, so the report's own title reads the way the owner says it.
UZ_MONTHS = [
    "yanvar", "fevral", "mart", "aprel", "may", "iyun",
    "iyul", "avgust", "sentabr", "oktabr", "noyabr", "dekabr",
]


def report_tz() -> ZoneInfo:
    return ZoneInfo(settings.report_timezone)


@dataclass(frozen=True)
class Period:
    """A closed calendar range, inclusive of both ends."""

    kind: PeriodKind
    start: date
    end: date
    label: str

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    def bounds_utc(self) -> tuple[datetime, datetime]:
        """Half-open UTC bounds for querying timestamp columns.

        The end is exclusive and taken as midnight *after* the last day, so a
        row stamped 23:59 on the final day is inside the period. Building it
        from ``end`` at 23:59:59 instead would silently drop the last minute.
        """
        tz = report_tz()
        start = datetime.combine(self.start, time.min, tzinfo=tz)
        end = datetime.combine(self.end + timedelta(days=1), time.min, tzinfo=tz)
        return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def resolve_period(kind: PeriodKind, offset: int = 0, today: date | None = None) -> Period:
    """The current period, or one ``offset`` periods back (1 = the previous one).

    Weeks run Monday to Sunday, which is how the working week is counted here.
    """
    today = today or datetime.now(report_tz()).date()

    if kind == "week":
        start = today - timedelta(days=today.weekday()) - timedelta(weeks=offset)
        end = start + timedelta(days=6)
        label = f"{start.strftime('%d.%m')} – {end.strftime('%d.%m.%Y')}"
        return Period(kind="week", start=start, end=end, label=label)

    month_index = today.year * 12 + (today.month - 1) - offset
    year, month = divmod(month_index, 12)
    month += 1
    start = date(year, month, 1)
    end = date(year, month, calendar.monthrange(year, month)[1])
    return Period(kind="month", start=start, end=end, label=f"{year} {UZ_MONTHS[month - 1]}")


@dataclass
class TruckLine:
    truck_id: str
    name: str
    plate_number: str
    distance_km: float = 0.0
    fuel_liters: float = 0.0
    fuel_cost: float = 0.0
    trips: int = 0
    revenue: float = 0.0
    expense_cost: float = 0.0
    maintenance_cost: float = 0.0

    @property
    def l_per_100km(self) -> float | None:
        # None, not 0: a truck with no recorded distance has *unknown*
        # consumption, and a zero on the row reads as an impossibly good one.
        if self.distance_km < 1:
            return None
        return round(self.fuel_liters / self.distance_km * 100, 1)

    @property
    def total_cost(self) -> float:
        return round(self.fuel_cost + self.expense_cost + self.maintenance_cost, 2)

    @property
    def profit(self) -> float:
        return round(self.revenue - self.total_cost, 2)


@dataclass
class DriverLine:
    driver_id: str
    name: str
    trips: int = 0
    revenue: float = 0.0
    expense_cost: float = 0.0


@dataclass
class PeriodReport:
    period: Period
    organization: str
    generated_at: datetime
    currency: str = "UZS"

    trips_delivered: int = 0
    trips_in_progress: int = 0
    revenue: float = 0.0
    fuel_cost: float = 0.0
    fuel_liters: float = 0.0
    expense_cost: float = 0.0
    maintenance_cost: float = 0.0
    distance_km: float = 0.0

    trucks: list[TruckLine] = field(default_factory=list)
    drivers: list[DriverLine] = field(default_factory=list)

    # Refuelling happens in big, irregular chunks while distance accrues every
    # day, so litres-per-100km over a short period measures how much fuel
    # happened to be *bought* in it, not how much was burned. In this fleet's
    # own demo data a month reads 36.5 L/100km and one week inside that month
    # reads 13.6 — the second number is noise, and it is exactly the sort of
    # number someone would use to praise a driver who did nothing different.
    fills: int = 0
    trucks_moved: int = 0

    # True when the period reaches back past the GPS retention horizon, so the
    # distance (and therefore L/100km) covers only part of it. Reported rather
    # than silently served: a fuel-efficiency figure computed from half the
    # distance is not a small error, it is double.
    distance_partial: bool = False

    @property
    def total_cost(self) -> float:
        return round(self.fuel_cost + self.expense_cost + self.maintenance_cost, 2)

    @property
    def profit(self) -> float:
        return round(self.revenue - self.total_cost, 2)

    @property
    def margin_pct(self) -> float:
        return round(self.profit / self.revenue * 100, 1) if self.revenue > 0 else 0.0

    @property
    def l_per_100km(self) -> float | None:
        if self.distance_km < 1:
            return None
        return round(self.fuel_liters / self.distance_km * 100, 1)

    @property
    def consumption_reliable(self) -> bool:
        """Whether ``l_per_100km`` is worth putting in front of anyone.

        Litres bought over a period is not litres burned in it: whatever was in
        the tank on the first day was paid for earlier, and whatever is left on
        the last day has not been used. Over a month that boundary error is
        small against the total. Over a week it dominates — this fleet's own
        demo data reads 36.5 L/100km for August and 13.6 and 110.6 for two
        weeks inside it. All three come from the same tank fills.

        The Leakage screen divides the same two numbers and is sound, because
        it never states the ratio as fact: it ranks each truck against the fleet
        median, and the boundary error is roughly common to every truck in the
        same window. A report that prints one absolute figure has no such cover.

        So: months only, and only when the distance is complete and enough
        refuelling actually happened to cover the trucks that moved.
        """
        if self.period.kind != "month":
            return False
        if self.distance_partial or self.distance_km < 1:
            return False
        if not self.trucks_moved or not self.fills:
            return False
        return self.fills >= self.trucks_moved


async def build_period_report(db: AsyncSession, org_id, period: Period) -> PeriodReport:
    """Aggregate one organization's money and movement over a calendar period."""
    start_utc, end_utc = period.bounds_utc()

    org_name = (
        await db.execute(select(Organization.name).where(Organization.id == org_id))
    ).scalar() or ""

    report = PeriodReport(
        period=period,
        organization=org_name,
        generated_at=datetime.now(timezone.utc),
    )

    trucks = (
        await db.execute(select(Truck).where(Truck.org_id == org_id).order_by(Truck.name))
    ).scalars().all()
    lines = {
        str(t.id): TruckLine(truck_id=str(t.id), name=t.name, plate_number=t.plate_number)
        for t in trucks
    }

    drivers = (
        await db.execute(select(Driver).where(Driver.org_id == org_id).order_by(Driver.name))
    ).scalars().all()
    driver_lines = {str(d.id): DriverLine(driver_id=str(d.id), name=d.name) for d in drivers}

    # ---- trips: revenue, recognised on delivery -----------------------------
    delivered = (
        await db.execute(
            select(Trip).where(
                Trip.org_id == org_id,
                Trip.status == TripStatus.delivered,
                Trip.delivered_at >= start_utc,
                Trip.delivered_at < end_utc,
            )
        )
    ).scalars().all()
    for trip in delivered:
        rate = float(trip.rate or 0)
        report.trips_delivered += 1
        report.revenue += rate
        if trip.truck_id and str(trip.truck_id) in lines:
            line = lines[str(trip.truck_id)]
            line.trips += 1
            line.revenue += rate
        if trip.driver_id and str(trip.driver_id) in driver_lines:
            d = driver_lines[str(trip.driver_id)]
            d.trips += 1
            d.revenue += rate

    report.trips_in_progress = (
        await db.execute(
            select(func.count(Trip.id)).where(
                Trip.org_id == org_id,
                Trip.status.notin_((TripStatus.delivered, TripStatus.cancelled)),
            )
        )
    ).scalar() or 0

    # ---- fuel ---------------------------------------------------------------
    report.fills = (
        await db.execute(
            select(func.count(FuelLog.id))
            .join(Truck, Truck.id == FuelLog.truck_id)
            .where(Truck.org_id == org_id, FuelLog.filled_at >= start_utc, FuelLog.filled_at < end_utc)
        )
    ).scalar() or 0

    fuel_rows = (
        await db.execute(
            select(FuelLog.truck_id, func.sum(FuelLog.liters), func.sum(FuelLog.total_cost))
            .join(Truck, Truck.id == FuelLog.truck_id)
            .where(Truck.org_id == org_id, FuelLog.filled_at >= start_utc, FuelLog.filled_at < end_utc)
            .group_by(FuelLog.truck_id)
        )
    ).all()
    for truck_id, liters, cost in fuel_rows:
        liters, cost = float(liters or 0), float(cost or 0)
        report.fuel_liters += liters
        report.fuel_cost += cost
        if str(truck_id) in lines:
            lines[str(truck_id)].fuel_liters += liters
            lines[str(truck_id)].fuel_cost += cost

    # ---- driver expenses ----------------------------------------------------
    expense_rows = (
        await db.execute(
            select(DriverExpense.driver_id, DriverExpense.truck_id, func.sum(DriverExpense.amount))
            .join(Driver, Driver.id == DriverExpense.driver_id)
            .where(
                Driver.org_id == org_id,
                DriverExpense.spent_at >= period.start,
                DriverExpense.spent_at <= period.end,
            )
            .group_by(DriverExpense.driver_id, DriverExpense.truck_id)
        )
    ).all()
    for driver_id, truck_id, amount in expense_rows:
        amount = float(amount or 0)
        report.expense_cost += amount
        if str(driver_id) in driver_lines:
            driver_lines[str(driver_id)].expense_cost += amount
        if truck_id and str(truck_id) in lines:
            lines[str(truck_id)].expense_cost += amount

    # ---- maintenance --------------------------------------------------------
    maint_rows = (
        await db.execute(
            select(MaintenanceRecord.truck_id, func.sum(MaintenanceRecord.cost))
            .join(Truck, Truck.id == MaintenanceRecord.truck_id)
            .where(
                Truck.org_id == org_id,
                MaintenanceRecord.performed_at >= period.start,
                MaintenanceRecord.performed_at <= period.end,
            )
            .group_by(MaintenanceRecord.truck_id)
        )
    ).all()
    for truck_id, cost in maint_rows:
        cost = float(cost or 0)
        report.maintenance_cost += cost
        if str(truck_id) in lines:
            lines[str(truck_id)].maintenance_cost += cost

    # ---- distance from GPS history -----------------------------------------
    retention = settings.gps_history_retention_days
    if retention > 0:
        horizon = (datetime.now(timezone.utc) - timedelta(days=retention)).date()
        report.distance_partial = period.start < horizon

    for truck in trucks:
        points = (
            await db.execute(
                select(TruckLocationHistory.latitude, TruckLocationHistory.longitude)
                .where(
                    TruckLocationHistory.truck_id == truck.id,
                    TruckLocationHistory.recorded_at >= start_utc,
                    TruckLocationHistory.recorded_at < end_utc,
                )
                .order_by(TruckLocationHistory.recorded_at)
            )
        ).all()
        km = 0.0
        for (lat1, lon1), (lat2, lon2) in zip(points, points[1:]):
            km += _haversine_km(float(lat1), float(lon1), float(lat2), float(lon2))
        lines[str(truck.id)].distance_km = round(km, 1)
        report.distance_km += km
        # 50 km, not "any movement": a truck that only shuffled around the yard
        # has not consumed enough to need a fill, and counting it would make the
        # reliability bar harder to clear for no reason.
        if km >= 50:
            report.trucks_moved += 1

    report.revenue = round(report.revenue, 2)
    report.fuel_cost = round(report.fuel_cost, 2)
    report.fuel_liters = round(report.fuel_liters, 1)
    report.expense_cost = round(report.expense_cost, 2)
    report.maintenance_cost = round(report.maintenance_cost, 2)
    report.distance_km = round(report.distance_km, 1)

    # Trucks that neither earned nor cost anything are noise on a one-page
    # document; the fleet total already counts them as owned.
    report.trucks = [
        line for line in lines.values()
        if line.revenue or line.total_cost or line.distance_km
    ]
    report.trucks.sort(key=lambda line: line.profit, reverse=True)
    report.drivers = [d for d in driver_lines.values() if d.trips or d.expense_cost]
    report.drivers.sort(key=lambda d: d.revenue, reverse=True)

    return report
