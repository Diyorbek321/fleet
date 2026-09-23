"""Circular geofences: which trucks crossed which boundary, and when.

The expensive part of this file is not the arithmetic — a haversine is a
handful of floating-point operations — it is the *state* question: was this
truck already inside the fence? Answered naively, that is one indexed query per
fence per position, and a tracker that buffers offline and then flushes fifty
points arrives with a batch that turns twenty fences into a thousand queries in
one request.

:func:`evaluate_track` answers it once per request instead. It reads each
fence's last known state a single time, then replays the whole batch against
that state in memory, so the query count depends on the number of fences and
not on the number of points. Replaying in memory also fixes something the
per-point version got wrong: events created for point 1 were added to the
session but not flushed, so point 2 re-read the *pre-batch* state from the
database and could emit a second ``enter`` for a boundary already crossed.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Iterable, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import GeofenceEventType
from app.models.geofences import Geofence, GeofenceEvent

EARTH_RADIUS_M = 6_371_000.0

# One position on a truck's track: where it was and when.
TrackPoint = tuple[float, float, Optional[datetime]]


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance between two WGS84 points, in meters."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


async def _last_states(db: AsyncSession, truck_id, fence_ids: Sequence) -> dict:
    """The most recent event per fence for this truck, in one round-trip.

    ``DISTINCT ON`` is Postgres-specific and this application is Postgres-only
    (asyncpg, ``insert().on_conflict_do_update``, advisory locks). The
    alternative — one ordered ``LIMIT 1`` per fence — is the query storm this
    module exists to avoid.
    """
    if not fence_ids:
        return {}
    rows = (
        await db.execute(
            select(GeofenceEvent)
            .where(
                GeofenceEvent.truck_id == truck_id,
                GeofenceEvent.geofence_id.in_(fence_ids),
            )
            .distinct(GeofenceEvent.geofence_id)
            .order_by(GeofenceEvent.geofence_id, GeofenceEvent.recorded_at.desc())
        )
    ).scalars().all()
    return {row.geofence_id: row for row in rows}


async def evaluate_track(
    db: AsyncSession,
    truck_id,
    points: Iterable[TrackPoint],
    org_id=None,
) -> list[GeofenceEvent]:
    """Detect enter/exit transitions along one truck's batch of positions.

    A transition is emitted only when the inside/outside state changes, so a
    truck parked inside a depot does not spam enter events on every ping.
    Points are evaluated in the order given — the caller sorts them, because
    only the caller knows whether a missing ``recorded_at`` means "now" or
    "unknown".

    Only fences belonging to ``org_id`` (the truck's organization) are
    evaluated, so a position never crosses another tenant's geofences.
    """
    points = list(points)
    if not points:
        return []

    stmt = select(Geofence).where(Geofence.active.is_(True))
    if org_id is not None:
        stmt = stmt.where(Geofence.org_id == org_id)
    fences = (await db.execute(stmt)).scalars().all()
    if not fences:
        return []

    last = await _last_states(db, truck_id, [f.id for f in fences])
    inside: dict = {
        f.id: (f.id in last and last[f.id].event == GeofenceEventType.enter)
        for f in fences
    }

    # Precompute what never changes across the batch.
    geometry = [(f.id, float(f.center_lat), float(f.center_lng), float(f.radius_m)) for f in fences]

    new_events: list[GeofenceEvent] = []
    for latitude, longitude, recorded_at in points:
        when = recorded_at or datetime.now(timezone.utc)
        for fence_id, center_lat, center_lng, radius_m in geometry:
            inside_now = haversine_m(latitude, longitude, center_lat, center_lng) <= radius_m
            if inside_now == inside[fence_id]:
                continue

            event = GeofenceEvent(
                geofence_id=fence_id,
                truck_id=truck_id,
                event=GeofenceEventType.enter if inside_now else GeofenceEventType.exit,
                latitude=latitude,
                longitude=longitude,
                recorded_at=when,
            )
            db.add(event)
            new_events.append(event)
            inside[fence_id] = inside_now

    return new_events


async def evaluate_geofences(
    db: AsyncSession,
    truck_id,
    latitude: float,
    longitude: float,
    recorded_at: Optional[datetime] = None,
    org_id=None,
) -> list[GeofenceEvent]:
    """Single-position convenience wrapper over :func:`evaluate_track`."""
    return await evaluate_track(
        db, truck_id, [(latitude, longitude, recorded_at)], org_id=org_id
    )
