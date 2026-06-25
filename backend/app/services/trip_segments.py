"""Segment a trip's GPS history into moving vs stopped stretches.

Replays the assigned truck's ``truck_location_history`` between the trip's start
and delivery (falling back to first/last available point when timestamps are
missing) and groups consecutive points by motion. A point is "moving" when its
recorded speed is above ``MOVING_SPEED_KMH``; a run of same-kind points becomes
one :class:`TripSegment`. Re-running replaces the trip's segments, so the result
is idempotent.
"""
from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import SegmentKind
from app.models.trips import Trip, TripSegment
from app.models.trucks import TruckLocationHistory

# Below this recorded speed (km/h) a point counts as stopped/idling.
MOVING_SPEED_KMH = 3.0
_EARTH_RADIUS_KM = 6371.0088


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance between two lat/lng points in kilometres."""
    rlat1, rlat2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlng / 2) ** 2
    return 2 * _EARTH_RADIUS_KM * math.asin(math.sqrt(a))


@dataclass
class _Point:
    lat: float
    lng: float
    speed: float
    recorded_at: datetime


def _kind_for(speed: float) -> SegmentKind:
    return SegmentKind.moving if speed >= MOVING_SPEED_KMH else SegmentKind.stopped


def _build_segments(trip_id: uuid.UUID, points: list[_Point]) -> list[TripSegment]:
    """Group consecutive same-kind points into ordered TripSegment rows."""
    segments: list[TripSegment] = []
    if not points:
        return segments

    seq = 0
    run = [points[0]]
    run_kind = _kind_for(points[0].speed)

    def _flush(run_points: list[_Point], kind: SegmentKind, seq: int) -> TripSegment:
        first, last = run_points[0], run_points[-1]
        distance = 0.0
        for a, b in zip(run_points, run_points[1:]):
            distance += _haversine_km(a.lat, a.lng, b.lat, b.lng)
        duration = max(0, int((last.recorded_at - first.recorded_at).total_seconds()))
        return TripSegment(
            trip_id=trip_id,
            seq=seq,
            kind=kind,
            started_at=first.recorded_at,
            ended_at=last.recorded_at,
            duration_s=duration,
            start_lat=first.lat,
            start_lng=first.lng,
            end_lat=last.lat,
            end_lng=last.lng,
            distance_km=round(distance, 3),
            point_count=len(run_points),
        )

    for pt in points[1:]:
        kind = _kind_for(pt.speed)
        if kind == run_kind:
            run.append(pt)
        else:
            segments.append(_flush(run, run_kind, seq))
            seq += 1
            run = [pt]
            run_kind = kind
    segments.append(_flush(run, run_kind, seq))
    return segments


async def segment_trip(db: AsyncSession, trip: Trip) -> list[TripSegment]:
    """(Re)compute and persist segments for a trip from its truck's GPS history.

    Returns the freshly stored segments ordered by ``seq``. Idempotent: existing
    segments for the trip are removed first. When the trip has no truck or no GPS
    history in range, the trip is left with zero segments.
    """
    await db.execute(delete(TripSegment).where(TripSegment.trip_id == trip.id))

    points: list[_Point] = []
    if trip.truck_id is not None:
        stmt = (
            select(TruckLocationHistory)
            .where(TruckLocationHistory.truck_id == trip.truck_id)
            .order_by(TruckLocationHistory.recorded_at)
        )
        if trip.started_at is not None:
            stmt = stmt.where(TruckLocationHistory.recorded_at >= trip.started_at)
        if trip.delivered_at is not None:
            stmt = stmt.where(TruckLocationHistory.recorded_at <= trip.delivered_at)

        rows = (await db.execute(stmt)).scalars().all()
        points = [
            _Point(
                lat=float(r.latitude),
                lng=float(r.longitude),
                speed=float(r.speed) if r.speed is not None else 0.0,
                recorded_at=r.recorded_at,
            )
            for r in rows
        ]

    segments = _build_segments(trip.id, points)
    for seg in segments:
        db.add(seg)
    await db.commit()

    res = await db.execute(
        select(TripSegment)
        .where(TripSegment.trip_id == trip.id)
        .order_by(TripSegment.seq)
    )
    return list(res.scalars().all())
