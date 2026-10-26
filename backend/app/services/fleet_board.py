"""The fleet board: every truck, where it is, and its export and import.

The sheet a dispatcher used to fill in by phone each morning — "Пустые авто из
РФ / ЭКСПОРТ / ИМПОРТ" — built from what the platform already knows: the
desk's own truck order, the place the GPS last labelled, and the trip each way
that is still under way.

"Still under way" is every status but delivered and cancelled: a delivered
trip belongs to the archive, and a truck whose import was delivered yesterday
has an empty import column today — that is the sheet's meaning of a blank.

**Empty ("порожний").** The sheet's first question is which trucks are
standing empty, and where. A truck is empty from the moment its last load is
unloaded until another load is booked. Where it was unloaded says what it is
waiting for: an export unloaded in Russia waits there for an import load
("импорт порожний — Москва"); an import unloaded at home waits for an export.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import TripStage, TripStatus
from app.models.trips import Trip, TripEvent
from app.models.trucks import Truck, TruckLocation
from app.services.period_reports import report_tz

EXPORT = "uz_ru"
IMPORT = "ru_uz"

# When a truck holds two open trips the same way, the one on the road is the
# one the sheet is about; the next booking waits its turn.
_STATUS_RANK: dict[TripStatus, int] = {
    TripStatus.at_border: 0,
    TripStatus.en_route: 1,
    TripStatus.loading: 2,
    TripStatus.planned: 3,
    TripStatus.draft: 4,
}
_CLOSED = (TripStatus.delivered, TripStatus.cancelled)

# Stages after which the load is off the truck, though the trip may stay open
# a day longer for papers.
_UNLOADED_STAGES = (TripStage.unloaded, TripStage.trip_completed)

# What a truck unloaded on a trip this way is now waiting for.
_WAITS_FOR = {EXPORT: "import", IMPORT: "export"}


@dataclass(frozen=True)
class BoardTrip:
    trip_id: uuid.UUID
    reference: str
    route: str
    loading_date: date | None
    unloading_date: date | None
    is_loaded: bool
    status: TripStatus
    customer: str | None = None


@dataclass(frozen=True)
class BoardEmpty:
    """The truck stands empty: where, since when, and which way it needs a load."""

    kind: str  # "export" or "import" — the load it is waiting for
    place: str | None
    since: datetime | None


@dataclass(frozen=True)
class BoardRow:
    position: int
    truck_id: uuid.UUID
    plate: str
    location: str | None
    location_at: datetime | None
    export_trip: BoardTrip | None
    import_trip: BoardTrip | None
    empty: BoardEmpty | None = None


def short_place(address: str | None) -> str | None:
    """"Казахстан, Шымкент" → "Шымкент": the sheet's column holds a town."""
    if not address:
        return None
    return address.rsplit(",", 1)[-1].strip() or None


def _local_date(moment: datetime | None) -> date | None:
    return moment.astimezone(report_tz()).date() if moment else None


def _route(trip: Trip) -> str:
    ends = [p.strip() for p in (trip.origin_name, trip.destination_name) if p and p.strip()]
    return " - ".join(ends) if ends else "—"


def _board_trip(trip: Trip) -> BoardTrip:
    return BoardTrip(
        trip_id=trip.id,
        reference=trip.reference,
        route=_route(trip),
        # The day it was actually loaded once a driver has said so; until then
        # the day it is booked to load.
        loading_date=_local_date(trip.loaded_at or trip.scheduled_start),
        unloading_date=_local_date(trip.scheduled_end),
        is_loaded=trip.is_loaded,
        status=trip.status,
        customer=trip.customer,
    )


def _current_by_truck(trips: list[Trip]) -> dict[tuple[uuid.UUID, str], Trip]:
    """The trip each truck is on, each way."""
    current: dict[tuple[uuid.UUID, str], Trip] = {}
    for trip in trips:
        key = (trip.truck_id, trip.direction)
        held = current.get(key)
        if held is None or _outranks(trip, held):
            current[key] = trip
    return current


def _outranks(trip: Trip, held: Trip) -> bool:
    rank, held_rank = _STATUS_RANK.get(trip.status, 9), _STATUS_RANK.get(held.status, 9)
    if rank != held_rank:
        return rank < held_rank
    return trip.created_at > held.created_at


def _is_unloaded(trip: Trip) -> bool:
    return trip.status == TripStatus.delivered or trip.current_stage in _UNLOADED_STAGES


async def _unloaded_at(db: AsyncSession, trip_ids: list[uuid.UUID]) -> dict[uuid.UUID, datetime]:
    """When each trip's driver reported "unloaded" — the moment the truck emptied."""
    if not trip_ids:
        return {}
    rows = await db.execute(
        select(TripEvent.trip_id, TripEvent.recorded_at)
        .where(TripEvent.trip_id.in_(trip_ids), TripEvent.stage == TripStage.unloaded)
        .order_by(TripEvent.recorded_at)
    )
    # Ascending, so a stage reported twice keeps the first time.
    unloaded: dict[uuid.UUID, datetime] = {}
    for trip_id, at in rows.all():
        unloaded.setdefault(trip_id, at)
    return unloaded


async def _empty_by_truck(
    db: AsyncSession, org_id: uuid.UUID, truck_ids: list[uuid.UUID]
) -> dict[uuid.UUID, BoardEmpty]:
    """Trucks whose last load is off and no next load is booked.

    Any open trip not yet unloaded — a load on board or one booked to load —
    means the truck is spoken for, and the board already shows that trip.
    """
    trips = (
        await db.execute(
            select(Trip).where(
                Trip.org_id == org_id,
                Trip.truck_id.in_(truck_ids),
                Trip.direction.in_((EXPORT, IMPORT)),
                Trip.status != TripStatus.cancelled,
            )
        )
    ).scalars().all()
    busy = {t.truck_id for t in trips if t.status not in _CLOSED and not _is_unloaded(t)}
    unloaded = [t for t in trips if t.truck_id not in busy and _is_unloaded(t)]
    unloaded_at = await _unloaded_at(db, [t.id for t in unloaded])

    def emptied(trip: Trip) -> datetime:
        return unloaded_at.get(trip.id) or trip.delivered_at or trip.updated_at

    latest: dict[uuid.UUID, Trip] = {}
    for trip in unloaded:
        held = latest.get(trip.truck_id)
        if held is None or emptied(trip) > emptied(held):
            latest[trip.truck_id] = trip
    return {
        truck_id: BoardEmpty(
            kind=_WAITS_FOR[trip.direction],
            place=short_place(trip.destination_name),
            since=emptied(trip),
        )
        for truck_id, trip in latest.items()
    }


async def build_board(db: AsyncSession, org_id: uuid.UUID) -> list[BoardRow]:
    trucks = (
        await db.execute(
            select(Truck)
            .where(Truck.org_id == org_id, Truck.is_enabled.is_(True))
            # The same order as the trucks page: the desk arranged it once.
            .order_by(Truck.sort_order.asc().nulls_last(), Truck.created_at.desc())
        )
    ).scalars().all()
    if not trucks:
        return []
    truck_ids = [t.id for t in trucks]

    locations = {
        loc.truck_id: loc
        for loc in (
            await db.execute(select(TruckLocation).where(TruckLocation.truck_id.in_(truck_ids)))
        ).scalars()
    }
    open_trips = (
        await db.execute(
            select(Trip).where(
                Trip.org_id == org_id,
                Trip.truck_id.in_(truck_ids),
                Trip.direction.in_((EXPORT, IMPORT)),
                Trip.status.not_in(_CLOSED),
            )
        )
    ).scalars().all()
    current = _current_by_truck(list(open_trips))
    empty = await _empty_by_truck(db, org_id, truck_ids)

    rows: list[BoardRow] = []
    for position, truck in enumerate(trucks, start=1):
        loc = locations.get(truck.id)
        export_trip = current.get((truck.id, EXPORT))
        import_trip = current.get((truck.id, IMPORT))
        rows.append(
            BoardRow(
                position=position,
                truck_id=truck.id,
                plate=truck.plate_number,
                location=short_place(loc.address) if loc else None,
                location_at=loc.recorded_at if loc else None,
                export_trip=_board_trip(export_trip) if export_trip else None,
                import_trip=_board_trip(import_trip) if import_trip else None,
                empty=empty.get(truck.id),
            )
        )
    return rows
