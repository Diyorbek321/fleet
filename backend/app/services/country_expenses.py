"""Per-trip spending broken down by the country it happened in.

The question this answers is the one an owner asks when a truck comes back
from a run: *where did the money go?* Not "what did the whole month cost" —
one lorry, one round trip, and inside it Kazakhstan, Russia and Uzbekistan as
three separate columns, each itemised by what the money was actually spent on.

The raw material already exists: the driver fills a "yo'l varaqasi" per trip
(:mod:`app.models.trip_reports`) whose expense lines are stored as
``(country, category, amount)`` cells. Three things stand between that form
and a report an owner can read:

**Currencies do not add up.** A Kazakh cell is tenge, a Russian one roubles, an
Uzbek one so'm. Summing them produces a number with no meaning, and comparing
"KZ 450 000" against "RU 180 000" is comparing tenge to roubles. So every
country block carries its own native currency *and* a USD equivalent, and only
the USD figures are ever compared or totalled across countries. Native amounts
are never rewritten — the driver's own number stays on the row.

**Fuel is the biggest line and lives elsewhere.** The form keeps diesel in its
own table, split into KZ / RF / DOHA / E1CARD columns. KZ and RF are cash
bought in those countries, so they belong in those countries' totals and are
folded in as a synthetic ``fuel`` category (carrying litres as well as money).
DOHA and E1CARD are fuel cards — not cash held in a country's currency — so
they stay out of the country blocks and are reported separately.

**A rate has to come from somewhere honest.** In order: the trip's own recorded
exchange (dollars handed over, tenge received — the rate that trip actually
got), then the organization's configured rate, then nothing at all. "Nothing"
is a real answer here: the USD column goes empty and the report says which
country is missing a rate, rather than converting at a number nobody chose.
Every block reports which of the three it used.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.drivers import Driver
from app.models.enums import TripReportCountry
from app.models.organizations import Organization
from app.models.trip_reports import TripCountryExpenseLine, TripExpenseReport, TripFuelRow
from app.models.trips import Trip
from app.models.trucks import Truck
from app.services.period_reports import report_tz

# What one country's money is called. One currency per country, which is what
# makes summing a country's own native column legitimate.
COUNTRY_CURRENCY: dict[str, str] = {
    TripReportCountry.kz.value: "KZT",
    TripReportCountry.ru.value: "RUB",
    TripReportCountry.uz.value: "UZS",
}

# Country order is west-to-east along the route an Uzbek fleet actually drives
# (load at home, cross Kazakhstan, deliver in Russia), so the report reads in
# the order the money was spent.
COUNTRY_ORDER: tuple[str, ...] = (
    TripReportCountry.uz.value,
    TripReportCountry.kz.value,
    TripReportCountry.ru.value,
)

# Which fuel column was paid for in which country's cash. DOHA and E1CARD are
# deliberately absent: they are cards, settled centrally, and attributing them
# to wherever the truck happened to be standing would invent a fact.
FUEL_COLUMN_COUNTRY: dict[str, str] = {
    "kz": TripReportCountry.kz.value,
    "rf": TripReportCountry.ru.value,
}
CARD_FUEL_COLUMNS: tuple[str, ...] = ("doha", "e1card")

# Categories that do not come from the form's expense grid but are still money
# spent in a country. Kept as normal category rows so a reader sees one list
# per country instead of a list plus a footnote.
FUEL_CATEGORY = "fuel"
INSURANCE_CATEGORY = "insurance"

# How many days back the report covers when the caller names no range. Long
# enough that a truck on a three-week round trip appears without the user
# having to widen anything.
DEFAULT_WINDOW_DAYS = 90

_RATE_SOURCE_TRIP = "trip"
_RATE_SOURCE_ORG = "org"
_RATE_SOURCE_MIXED = "mixed"


def _num(v) -> float:
    return float(v) if v is not None else 0.0


@dataclass(frozen=True)
class Rates:
    """USD conversion rates for one trip, and where each came from.

    ``None`` is a first-class value: it means no rate was available, and the
    caller must leave the USD figure empty rather than guessing one.
    """

    kzt: float | None = None
    rub: float | None = None
    uzs: float | None = None
    kzt_source: str | None = None
    rub_source: str | None = None
    uzs_source: str | None = None

    def for_country(self, country: str) -> tuple[float | None, str | None]:
        if country == TripReportCountry.kz.value:
            return self.kzt, self.kzt_source
        if country == TripReportCountry.ru.value:
            return self.rub, self.rub_source
        return self.uzs, self.uzs_source


def _implied_rate(given, received) -> float | None:
    """The rate a trip actually got, from its own exchange row.

    ``given`` dollars were handed over and ``received`` units came back, so the
    quotient is the rate on the day, at the booth, including whatever spread
    the changer took — a truer number for this trip than any published rate.
    Both sides must be positive: a form filled on one side only says nothing.
    """
    g, r = _num(given), _num(received)
    if g <= 0 or r <= 0:
        return None
    return round(r / g, 4)


def resolve_rates(report: TripExpenseReport | None, org: Organization | None) -> Rates:
    """Trip's own exchange first, the organization's configured rate second.

    The so'm has no trip-level source — the form records dollars changed into
    tenge and roubles, never into so'm, because the driver leaves home with
    so'm already in hand — so UZS always falls back to the org rate.
    """
    kzt = _implied_rate(report.usd_to_kzt_given, report.usd_to_kzt_received) if report else None
    rub = _implied_rate(report.usd_to_rub_given, report.usd_to_rub_received) if report else None
    kzt_source = _RATE_SOURCE_TRIP if kzt else None
    rub_source = _RATE_SOURCE_TRIP if rub else None

    org_kzt = _num(org.usd_to_kzt) if org and org.usd_to_kzt else None
    org_rub = _num(org.usd_to_rub) if org and org.usd_to_rub else None
    org_uzs = _num(org.usd_to_uzs) if org and org.usd_to_uzs else None

    if kzt is None and org_kzt:
        kzt, kzt_source = org_kzt, _RATE_SOURCE_ORG
    if rub is None and org_rub:
        rub, rub_source = org_rub, _RATE_SOURCE_ORG

    uzs = org_uzs or None
    uzs_source = _RATE_SOURCE_ORG if uzs else None

    return Rates(
        kzt=kzt, rub=rub, uzs=uzs,
        kzt_source=kzt_source, rub_source=rub_source, uzs_source=uzs_source,
    )


def _to_usd(amount: float, rate: float | None) -> float | None:
    if not rate or rate <= 0:
        return None
    return round(amount / rate, 2)


@dataclass
class CategoryLine:
    """One thing money was spent on, in one country."""

    category: str
    amount: float
    amount_usd: float | None = None
    # Only ``fuel`` carries litres; everything else has no natural unit.
    liters: float | None = None


@dataclass
class CountryBlock:
    """Everything spent in one country, itemised."""

    country: str
    currency: str
    lines: list[CategoryLine] = field(default_factory=list)
    total: float = 0.0
    total_usd: float | None = None
    fuel_liters: float = 0.0
    rate: float | None = None
    rate_source: str | None = None

    @property
    def is_empty(self) -> bool:
        return self.total == 0 and self.fuel_liters == 0


@dataclass
class CardFuel:
    """Diesel bought on a fuel card, which belongs to no country."""

    column: str
    liters: float = 0.0
    amount: float = 0.0


@dataclass
class TripRow:
    """One round trip of one truck, with its money split three ways."""

    trip_id: str
    reference: str
    truck_id: str | None
    truck_name: str | None
    plate_number: str | None
    driver_name: str | None
    trip_date: date | None
    route: str | None
    distance_km: float | None
    report_status: str | None
    countries: list[CountryBlock] = field(default_factory=list)
    cards: list[CardFuel] = field(default_factory=list)
    total_usd: float | None = None
    # True when a country on this trip had spending but no rate, so the USD
    # total covers only part of what was spent. Shown, never silently dropped.
    usd_partial: bool = False


@dataclass
class CountryExpenseReport:
    organization: str
    start: date
    end: date
    generated_at: datetime
    truck_id: str | None
    trips: list[TripRow] = field(default_factory=list)
    countries: list[CountryBlock] = field(default_factory=list)
    cards: list[CardFuel] = field(default_factory=list)
    total_usd: float | None = None
    usd_partial: bool = False
    # Countries that have spending in this range but no usable rate anywhere.
    # The UI turns this into "set a rate in Settings", which is the only thing
    # that will fix the missing USD column.
    countries_missing_rate: list[str] = field(default_factory=list)


def _distance_for(trip: Trip, report: TripExpenseReport | None) -> float | None:
    """Kilometres for the round trip, preferring what the odometer recorded.

    The odometer is the driver's own reading of the same trip the expenses came
    from, so it belongs to the same document; the planned distance is a
    dispatcher's estimate and is only a fallback.
    """
    if report and report.odometer_out is not None and report.odometer_in is not None:
        travelled = _num(report.odometer_in) - _num(report.odometer_out)
        if travelled > 0:
            return round(travelled, 1)
    if trip.planned_distance_km is not None:
        return round(_num(trip.planned_distance_km), 1)
    return None


def _route_for(trip: Trip, report: TripExpenseReport | None) -> str | None:
    if report and report.route_text:
        return report.route_text
    if trip.origin_name or trip.destination_name:
        return f"{trip.origin_name or '—'} → {trip.destination_name or '—'}"
    return None


def _trip_date(trip: Trip, report: TripExpenseReport | None) -> date | None:
    """The day this trip is filed under.

    The report's own date is the driver's answer and wins. Otherwise the trip is
    filed by delivery — that is when the run finished and the spending stopped —
    falling back to departure for a truck still on the road.
    """
    if report and report.report_date:
        return report.report_date
    tz = report_tz()
    stamp = trip.delivered_at or trip.started_at or trip.created_at
    return stamp.astimezone(tz).date() if stamp else None


def build_trip_row(
    trip: Trip,
    report: TripExpenseReport | None,
    org: Organization | None,
    *,
    truck_name: str | None = None,
    truck_plate: str | None = None,
    driver_name: str | None = None,
) -> TripRow:
    """Turn one trip and its driver-filled form into a country-by-country row.

    Truck and driver names are passed in rather than read off ``trip``: ``Trip``
    holds plain FKs with no ORM relationships, so the caller resolves them once
    in the same joined query that fetched the trips.
    """
    fuel_rows: list[TripFuelRow] = list(report.fuel_rows) if report else []
    lines: list[TripCountryExpenseLine] = list(report.country_expenses) if report else []
    rates = resolve_rates(report, org)

    # Country → category → (amount, litres). Litres only ever come from fuel.
    buckets: dict[str, dict[str, list[float]]] = {c: {} for c in COUNTRY_ORDER}

    def add(country: str, category: str, amount: float, liters: float = 0.0) -> None:
        if amount == 0 and liters == 0:
            return
        slot = buckets[country].setdefault(category, [0.0, 0.0])
        slot[0] += amount
        slot[1] += liters

    for line in lines:
        add(line.country.value, line.category.value, _num(line.amount))

    for column, country in FUEL_COLUMN_COUNTRY.items():
        amount = sum(_num(getattr(row, f"{column}_amount")) for row in fuel_rows)
        liters = sum(_num(getattr(row, f"{column}_liters")) for row in fuel_rows)
        add(country, FUEL_CATEGORY, amount, liters)

    if report:
        add(TripReportCountry.kz.value, INSURANCE_CATEGORY, _num(report.insurance_kz))
        add(TripReportCountry.ru.value, INSURANCE_CATEGORY, _num(report.insurance_rf))

    countries: list[CountryBlock] = []
    total_usd = 0.0
    usd_known = False
    usd_partial = False

    for country in COUNTRY_ORDER:
        rate, source = rates.for_country(country)
        block = CountryBlock(
            country=country,
            currency=COUNTRY_CURRENCY[country],
            rate=rate,
            rate_source=source,
        )
        for category, (amount, liters) in buckets[country].items():
            block.lines.append(
                CategoryLine(
                    category=category,
                    amount=round(amount, 2),
                    amount_usd=_to_usd(round(amount, 2), rate),
                    liters=round(liters, 2) if category == FUEL_CATEGORY and liters else None,
                )
            )
            block.total += amount
            if category == FUEL_CATEGORY:
                block.fuel_liters += liters

        # Biggest line first: the reason a trip cost what it did is almost
        # always at the top, and an owner should not have to hunt for it.
        block.lines.sort(key=lambda l: l.amount, reverse=True)
        block.total = round(block.total, 2)
        block.fuel_liters = round(block.fuel_liters, 2)
        block.total_usd = _to_usd(block.total, rate)

        if block.total_usd is not None:
            total_usd += block.total_usd
            usd_known = True
        elif block.total > 0:
            usd_partial = True

        countries.append(block)

    cards = []
    for column in CARD_FUEL_COLUMNS:
        amount = sum(_num(getattr(row, f"{column}_amount")) for row in fuel_rows)
        liters = sum(_num(getattr(row, f"{column}_liters")) for row in fuel_rows)
        if amount or liters:
            cards.append(CardFuel(column=column, liters=round(liters, 2), amount=round(amount, 2)))

    # The form wins over the fleet record: a paper "yo'l varaqasi" can name a
    # substitute driver or a swapped trailer, and that is the truth for this trip.
    driver = (report.driver_name if report and report.driver_name else None) or driver_name
    plate = (report.plate_number if report and report.plate_number else None) or truck_plate

    return TripRow(
        trip_id=str(trip.id),
        reference=trip.reference,
        truck_id=str(trip.truck_id) if trip.truck_id else None,
        truck_name=truck_name,
        plate_number=plate,
        driver_name=driver,
        trip_date=_trip_date(trip, report),
        route=_route_for(trip, report),
        distance_km=_distance_for(trip, report),
        report_status=report.status.value if report and report.status else None,
        countries=countries,
        cards=cards,
        total_usd=round(total_usd, 2) if usd_known else None,
        usd_partial=usd_partial,
    )


def aggregate(rows: list[TripRow]) -> tuple[list[CountryBlock], list[CardFuel], float | None, bool, list[str]]:
    """Roll per-trip rows up into fleet-wide country blocks.

    Native amounts are summed per country because a country has one currency;
    across countries only the USD figures are added, and each line keeps the
    USD its own trip's rate produced rather than being re-converted at some
    fleet-wide average.

    The effective rate is only shown for a country every trip converted. Where
    some trips had a rate and others did not, ``total / total_usd`` is not a
    rate at all — it divides all the spending by only the converted part — so
    the block reports no rate and is flagged as partial instead.
    """
    # category → [native, litres, usd, any_usd]. The USD is carried per line so
    # a line never has to be re-derived from a rate that may not exist.
    totals: dict[str, dict[str, list[float]]] = {c: {} for c in COUNTRY_ORDER}
    sources: dict[str, set[str]] = {c: set() for c in COUNTRY_ORDER}
    spent_without_rate: set[str] = set()
    card_totals: dict[str, CardFuel] = {}

    for row in rows:
        for block in row.countries:
            for line in block.lines:
                slot = totals[block.country].setdefault(line.category, [0.0, 0.0, 0.0, 0.0])
                slot[0] += line.amount
                slot[1] += line.liters or 0.0
                if line.amount_usd is not None:
                    slot[2] += line.amount_usd
                    slot[3] = 1.0
            if block.rate_source:
                sources[block.country].add(block.rate_source)
            if block.total > 0 and block.total_usd is None:
                spent_without_rate.add(block.country)
        for card in row.cards:
            acc = card_totals.setdefault(card.column, CardFuel(column=card.column))
            acc.liters = round(acc.liters + card.liters, 2)
            acc.amount = round(acc.amount + card.amount, 2)

    blocks: list[CountryBlock] = []
    grand_usd = 0.0
    any_usd = False

    for country in COUNTRY_ORDER:
        block = CountryBlock(country=country, currency=COUNTRY_CURRENCY[country])
        usd_total = 0.0
        usd_known = False

        for category, (amount, liters, usd, converted) in totals[country].items():
            block.lines.append(
                CategoryLine(
                    category=category,
                    amount=round(amount, 2),
                    amount_usd=round(usd, 2) if converted else None,
                    liters=round(liters, 2) if category == FUEL_CATEGORY and liters else None,
                )
            )
            block.total += amount
            if category == FUEL_CATEGORY:
                block.fuel_liters += liters
            if converted:
                usd_total += usd
                usd_known = True

        block.total = round(block.total, 2)
        block.fuel_liters = round(block.fuel_liters, 2)
        block.total_usd = round(usd_total, 2) if usd_known else None

        fully_converted = country not in spent_without_rate
        if fully_converted and block.total_usd and block.total:
            # Every trip converted, so the quotient is a real spend-weighted
            # rate. Restating the lines from it keeps them adding up to the
            # block total instead of drifting apart by rounding.
            effective = round(block.total / block.total_usd, 4)
            block.rate = effective
            for line in block.lines:
                line.amount_usd = _to_usd(line.amount, effective)

        found = sources[country]
        block.rate_source = _RATE_SOURCE_MIXED if len(found) > 1 else next(iter(found), None)
        block.lines.sort(key=lambda l: l.amount, reverse=True)

        if block.total_usd is not None:
            grand_usd += block.total_usd
            any_usd = True

        blocks.append(block)

    cards = [card_totals[c] for c in CARD_FUEL_COLUMNS if c in card_totals]
    missing = [c for c in COUNTRY_ORDER if c in spent_without_rate]
    partial = bool(missing)
    return blocks, cards, (round(grand_usd, 2) if any_usd else None), partial, missing


def default_range(today: date | None = None) -> tuple[date, date]:
    """The range used when the caller names none: the last ``DEFAULT_WINDOW_DAYS``."""
    end = today or datetime.now(report_tz()).date()
    return end - timedelta(days=DEFAULT_WINDOW_DAYS - 1), end


def _bounds_utc(start: date, end: date) -> tuple[datetime, datetime]:
    """Half-open UTC bounds for a local date range, end exclusive.

    Local, not UTC: a day that starts at 00:00 UTC starts at 05:00 in Tashkent,
    which would file the first five hours of the day into the day before.
    """
    tz = report_tz()
    lo = datetime.combine(start, time.min, tzinfo=tz)
    hi = datetime.combine(end + timedelta(days=1), time.min, tzinfo=tz)
    return lo.astimezone(timezone.utc), hi.astimezone(timezone.utc)


def _trips_in_range(org_id: uuid.UUID, start: date, end: date, truck_id: uuid.UUID | None) -> Select:
    """Trips of one org whose run falls in the range, newest first.

    A trip is dated by delivery, because that is when the run — and its
    spending — finished. A truck still on the road has no delivery date, so it
    falls back to departure and appears in the range it left in, rather than
    vanishing from the report until it arrives.
    """
    lo, hi = _bounds_utc(start, end)
    filed_at = func.coalesce(Trip.delivered_at, Trip.started_at, Trip.created_at)

    stmt = (
        select(Trip, Truck.name, Truck.plate_number, Driver.name)
        .select_from(Trip)
        .outerjoin(Truck, Truck.id == Trip.truck_id)
        .outerjoin(Driver, Driver.id == Trip.driver_id)
        .where(Trip.org_id == org_id, filed_at >= lo, filed_at < hi)
        .order_by(filed_at.desc())
    )
    if truck_id is not None:
        stmt = stmt.where(Trip.truck_id == truck_id)
    return stmt


async def build_country_expense_report(
    db: AsyncSession,
    org_id: uuid.UUID,
    *,
    start: date,
    end: date,
    truck_id: uuid.UUID | None = None,
) -> CountryExpenseReport:
    """Every trip in the range, each split into UZ / KZ / RU spending.

    Trips with no filled form are left out rather than listed as zeros: a row of
    empty columns reads as "this trip cost nothing", which is the one thing it
    definitely does not mean.
    """
    org = (
        await db.execute(select(Organization).where(Organization.id == org_id))
    ).scalar_one_or_none()

    trips = list((await db.execute(_trips_in_range(org_id, start, end, truck_id))).all())

    reports_by_trip: dict[uuid.UUID, TripExpenseReport] = {}
    if trips:
        res = await db.execute(
            select(TripExpenseReport)
            .where(
                TripExpenseReport.org_id == org_id,
                TripExpenseReport.trip_id.in_([t.id for t, *_ in trips]),
            )
            .options(
                selectinload(TripExpenseReport.fuel_rows),
                selectinload(TripExpenseReport.country_expenses),
            )
        )
        reports_by_trip = {r.trip_id: r for r in res.scalars().all()}

    rows: list[TripRow] = []
    for trip, truck_name, truck_plate, driver_name in trips:
        report = reports_by_trip.get(trip.id)
        if report is None:
            continue
        row = build_trip_row(
            trip, report, org,
            truck_name=truck_name, truck_plate=truck_plate, driver_name=driver_name,
        )
        if any(not b.is_empty for b in row.countries) or row.cards:
            rows.append(row)

    blocks, cards, total_usd, partial, missing = aggregate(rows)

    return CountryExpenseReport(
        organization=org.name if org else "",
        start=start,
        end=end,
        generated_at=datetime.now(timezone.utc),
        truck_id=str(truck_id) if truck_id else None,
        trips=rows,
        countries=blocks,
        cards=cards,
        total_usd=total_usd,
        usd_partial=partial,
        countries_missing_rate=missing,
    )
