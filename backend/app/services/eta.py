"""When the load reaches customs — the one date the cargo owner actually asks for.

Two estimators, tried in that order:

1. **Empirical.** The median time this fleet has really taken from the
   checkpoint the truck is at now to ``arrived_customs``, on this corridor.
   Border queues, weekends, a driver who always stops in Shymkent — none of
   that is in any formula, and all of it is in the median.
2. **Parametric.** Remaining road distance over the truck's own measured pace,
   plus an allowance for each border still ahead. Used until a corridor has
   enough history to speak for itself, which on a new customer is every trip
   for the first month.

Both answer a **date**, never a timestamp. A truck three days out cannot be
placed to the hour, and an owner who is told 14:30 and gets 21:00 stops reading
the message. The estimate also carries how it was made, so the message can say
"ориентировочно" when it is the formula talking.

The parametric estimator treats the customs terminal as the destination. On
these corridors it effectively is — an import clears in a terminal in or beside
the destination city — and where it is not, the empirical estimator learns the
real offset from the first handful of trips and takes over.
"""
from __future__ import annotations

import math
import statistics
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import TripStage
from app.models.trips import Trip, TripEvent

__all__ = [
    "Estimate",
    "corridor_key",
    "estimate_customs_arrival",
    "road_km",
    "borders_ahead",
]


# Great-circle distance times this is roughly what the road actually runs on
# the Tashkent–Moscow corridors: motorways bend around the Aral, the Urals and
# every border town. Measured against a handful of real trips rather than
# guessed; it is the single knob to turn if the parametric estimate drifts.
ROAD_FACTOR = 1.25

# Fallback pace for a truck that has not moved far enough to time itself yet.
# 430 km/day is what a single driver sustains here once rest, fuel stops and
# weighbridges are counted — not the 900 km the odometer allows in theory.
DEFAULT_KM_PER_DAY = 430.0

# A truck reporting less than this is stuck, not slow, and dividing by its pace
# would put the arrival in the next decade. A truck reporting more than this is
# a GPS artefact. Both are clamped rather than trusted.
MIN_KM_PER_DAY = 250.0
MAX_KM_PER_DAY = 900.0

# What one crossing costs, door to door, including the queue on both sides.
# Deliberately generous: an estimate that slips later is a complaint, an
# estimate that arrives early is a pleasant surprise.
BORDER_HOURS = 14.0

# Below this many past trips the median is one driver's bad week, not a
# corridor's behaviour, so the formula keeps the floor.
MIN_SAMPLES = 5

# The crossings a corridor can contain, in the order a UZ↔RU run meets them.
_CROSSINGS_SOUTH_TO_NORTH = ("uz_kz", "kz_ru")


@dataclass(frozen=True)
class Estimate:
    """A date, and an honest account of where it came from."""

    day: date
    #: ``"history"`` when the fleet's own past trips answered, ``"model"`` when
    #: the formula did. The message wording depends on it.
    basis: str
    #: How many past trips backed a ``"history"`` estimate; 0 for ``"model"``.
    samples: int = 0

    @property
    def is_measured(self) -> bool:
        return self.basis == "history"


def road_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Road distance between two points, approximated from the great circle."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a)) * ROAD_FACTOR


def corridor_key(trip: Trip) -> str:
    """A stable name for "this route", used to pool past trips.

    Only the first comma-separated part of each endpoint, lowercased: a
    dispatcher types "Ташкент" one day and "Ташкент, Сергели" the next, and
    those are the same corridor for the purpose of how long it takes.
    """

    def head(name: str | None) -> str:
        return (name or "").split(",")[0].strip().casefold() or "?"

    return f"{head(trip.origin_name)}>{head(trip.destination_name)}"


def borders_ahead(stage: TripStage | None, place: str | None) -> int:
    """How many crossings the truck still has to clear before customs.

    Counted from where it is rather than from a route plan, because the route
    plan is the thing that is usually missing. A truck that has just cleared
    UZ–KZ has one crossing left on a UZ↔RU run; one sitting at KZ–RU has that
    one still to clear.
    """
    if stage is None:
        return len(_CROSSINGS_SOUTH_TO_NORTH)
    if stage in (TripStage.arrived_customs, TripStage.left_customs,
                 TripStage.arrived_unloading, TripStage.unloaded):
        return 0
    if place not in _CROSSINGS_SOUTH_TO_NORTH:
        # Not at a border: everything the corridor holds is still ahead.
        return len(_CROSSINGS_SOUTH_TO_NORTH)

    index = _CROSSINGS_SOUTH_TO_NORTH.index(place)
    remaining = len(_CROSSINGS_SOUTH_TO_NORTH) - index
    # Having *crossed* this one means it no longer counts; standing at it means
    # it does.
    return remaining - 1 if stage is TripStage.crossed_border else remaining


def pace_km_per_day(covered_km: float, elapsed: timedelta) -> float:
    """The truck's own pace, clamped, or the corridor default when too early.

    Self-calibrating on purpose: a loaded reefer in February and an empty tilt
    in June do not move at the same speed, and the truck has already told us
    which one it is by how far it got.
    """
    days = elapsed.total_seconds() / 86400
    if days < 1 or covered_km <= 0:
        return DEFAULT_KM_PER_DAY
    return max(MIN_KM_PER_DAY, min(MAX_KM_PER_DAY, covered_km / days))


def model_hours(
    remaining_km: float, km_per_day: float, crossings_ahead: int
) -> float:
    """Driving time plus the queues still ahead, in hours."""
    driving = (remaining_km / max(km_per_day, MIN_KM_PER_DAY)) * 24
    return driving + crossings_ahead * BORDER_HOURS


async def median_hours_to_customs(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    corridor: str,
    stage: TripStage,
) -> tuple[float, int] | None:
    """Median hours from ``stage`` to customs on past trips of this corridor.

    Returns ``None`` below :data:`MIN_SAMPLES` so the caller falls back rather
    than quoting one lucky trip as if it were a pattern.
    """
    rows = (
        await db.execute(
            select(TripEvent.trip_id, TripEvent.stage, TripEvent.recorded_at, Trip.origin_name,
                   Trip.destination_name)
            .join(Trip, Trip.id == TripEvent.trip_id)
            .where(
                Trip.org_id == org_id,
                TripEvent.stage.in_((stage, TripStage.arrived_customs)),
            )
            .order_by(TripEvent.recorded_at)
        )
    ).all()

    # first sighting of `stage`, and the customs arrival that followed it
    seen: dict[uuid.UUID, datetime] = {}
    spans: list[float] = []
    for trip_id, row_stage, recorded_at, origin, destination in rows:
        if corridor_key(Trip(origin_name=origin, destination_name=destination)) != corridor:
            continue
        if row_stage is stage:
            seen.setdefault(trip_id, recorded_at)
        elif row_stage is TripStage.arrived_customs and trip_id in seen:
            hours = (recorded_at - seen.pop(trip_id)).total_seconds() / 3600
            if hours > 0:
                spans.append(hours)

    if len(spans) < MIN_SAMPLES:
        return None
    return statistics.median(spans), len(spans)


async def estimate_customs_arrival(
    db: AsyncSession,
    trip: Trip,
    *,
    current_lat: float | None,
    current_lng: float | None,
    covered_km: float | None = None,
    now: datetime | None = None,
) -> Estimate | None:
    """The date this load is expected to reach customs, or ``None`` if unknowable.

    ``None`` is a real answer and the message must print nothing rather than a
    number: a trip with no destination on file and no history behind it cannot
    be estimated, and inventing a date there is how the whole feature loses its
    credibility on the first run.
    """
    now = now or datetime.now(timezone.utc)

    if trip.current_stage in (TripStage.arrived_customs, TripStage.left_customs,
                              TripStage.arrived_unloading, TripStage.unloaded):
        return None  # already there; the question has been answered by events

    if trip.current_stage is not None:
        measured = await median_hours_to_customs(
            db,
            org_id=trip.org_id,
            corridor=corridor_key(trip),
            stage=trip.current_stage,
        )
        if measured is not None:
            hours, samples = measured
            return Estimate((now + timedelta(hours=hours)).date(), "history", samples)

    if trip.destination_lat is None or trip.destination_lng is None:
        return None
    if current_lat is None or current_lng is None:
        return None

    remaining = road_km(
        float(current_lat), float(current_lng),
        float(trip.destination_lat), float(trip.destination_lng),
    )
    elapsed = now - (trip.started_at or trip.created_at)
    pace = pace_km_per_day(covered_km or 0.0, elapsed)
    hours = model_hours(remaining, pace, borders_ahead(trip.current_stage, trip.current_stage_place))
    return Estimate((now + timedelta(hours=hours)).date(), "model")
