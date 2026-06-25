from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import GeofenceEventType
from app.models.geofences import Geofence, GeofenceEvent

EARTH_RADIUS_M = 6_371_000.0


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance between two WGS84 points, in meters."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


async def evaluate_geofences(
    db: AsyncSession,
    truck_id,
    latitude: float,
    longitude: float,
    recorded_at: Optional[datetime] = None,
    org_id=None,
) -> list[GeofenceEvent]:
    """Detect enter/exit transitions for a truck position against active fences.

    A transition is emitted only when the inside/outside state changes versus the
    truck's most recent event for that fence — so a truck parked inside a depot
    does not spam enter events on every GPS ping.

    Only fences belonging to ``org_id`` (the truck's organization) are evaluated,
    so a position never crosses another tenant's geofences.
    """
    recorded_at = recorded_at or datetime.now(timezone.utc)

    stmt = select(Geofence).where(Geofence.active.is_(True))
    if org_id is not None:
        stmt = stmt.where(Geofence.org_id == org_id)
    fences = (await db.execute(stmt)).scalars().all()
    if not fences:
        return []

    new_events: list[GeofenceEvent] = []
    for fence in fences:
        distance = haversine_m(latitude, longitude, float(fence.center_lat), float(fence.center_lng))
        inside_now = distance <= float(fence.radius_m)

        last = (
            await db.execute(
                select(GeofenceEvent)
                .where(GeofenceEvent.truck_id == truck_id, GeofenceEvent.geofence_id == fence.id)
                .order_by(GeofenceEvent.recorded_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        was_inside = last is not None and last.event == GeofenceEventType.enter

        if inside_now == was_inside:
            continue  # no boundary crossing

        event = GeofenceEvent(
            geofence_id=fence.id,
            truck_id=truck_id,
            event=GeofenceEventType.enter if inside_now else GeofenceEventType.exit,
            latitude=latitude,
            longitude=longitude,
            recorded_at=recorded_at,
        )
        db.add(event)
        new_events.append(event)

    return new_events
