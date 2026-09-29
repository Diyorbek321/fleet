"""Writing positions: latest state, history, and the truck's derived status.

Three things happen when a truck reports where it is. Two of them are about the
*newest* fix only — ``truck_locations`` holds one row per truck and the status
badge on the dashboard describes the truck right now — while the third,
``truck_location_history``, keeps every fix forever (well, for
``GPS_HISTORY_RETENTION_DAYS``).

That distinction is the whole reason :func:`record_positions` exists. A tracker
flushing a buffered batch used to run all three per point, so ten points meant
ten latest-location upserts that immediately overwrote each other and ten
``UPDATE trucks`` statements setting a status that only the last one would keep.
Appending ten history rows and settling the other two once is not an
optimisation of the same work — it is the work, with the redundancy removed.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Sequence

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import TruckStatus
from app.models.trucks import Truck, TruckLocation, TruckLocationHistory


def status_from_speed(speed_kmh: float) -> TruckStatus:
    # You can tune thresholds:
    if speed_kmh is None:
        return TruckStatus.offline
    if speed_kmh >= 5:
        return TruckStatus.moving
    if 0.5 <= speed_kmh < 5:
        return TruckStatus.idle
    return TruckStatus.stopped


@dataclass(frozen=True)
class Position:
    """One reported fix, normalised for the writer."""

    latitude: float
    longitude: float
    speed: float = 0.0
    heading: Optional[float] = None
    address: Optional[str] = None
    recorded_at: Optional[datetime] = None

    def when(self, *, now: Optional[datetime] = None) -> datetime:
        """The moment this fix describes.

        ``now`` is passed in by :func:`record_positions` so one request resolves
        a missing ``recorded_at`` to a single instant. Calling
        ``datetime.now()`` afresh for each use would let the history row and the
        latest-location row disagree about when the same fix happened.
        """
        return self.recorded_at or now or datetime.now(timezone.utc)


async def record_positions(
    db: AsyncSession,
    truck_id,
    positions: Sequence[Position],
    truck: Optional[Truck] = None,
) -> int:
    """Persist a batch of fixes for one truck, oldest first.

    The caller orders ``positions`` — only it knows whether a missing
    ``recorded_at`` means "now" or "unknown" — and the last entry is taken as
    the truck's current state.

    ``truck`` lets a caller that already holds the row hand it over. Every
    caller does: the ingest endpoint loaded it to check the tenant, the driver
    endpoint loaded it to check the assignment. Re-selecting it here was a
    second query per position on the hottest path in the application.

    Returns the number of positions written.
    """
    if not positions:
        return 0

    # One clock reading for the whole batch.
    now = datetime.now(timezone.utc)

    # History first: these are plain inserts with no read-back, so the session
    # flushes them together as one statement when the upsert below forces a
    # flush. One row per ping is the point of the table.
    for p in positions:
        db.add(TruckLocationHistory(
            truck_id=truck_id,
            latitude=p.latitude,
            longitude=p.longitude,
            speed=p.speed,
            heading=p.heading,
            recorded_at=p.when(now=now),
        ))

    latest = positions[-1]
    latest_at = latest.when(now=now)
    stmt = insert(TruckLocation).values(
        truck_id=truck_id,
        latitude=latest.latitude,
        longitude=latest.longitude,
        speed=latest.speed or 0,
        heading=latest.heading,
        address=latest.address,
        recorded_at=latest_at,
    )
    await db.execute(
        stmt.on_conflict_do_update(
            index_elements=["truck_id"],
            set_={
                "latitude": latest.latitude,
                "longitude": latest.longitude,
                "speed": latest.speed or 0,
                "heading": latest.heading,
                # Neither phones nor GT06 trackers send a place name, so a
                # plain overwrite blanked the label the scheduler's geocoding
                # job had just written — on every ping. Keep the old label
                # until that job relabels the new position; a place name one
                # tick stale beats an empty cell.
                "address": func.coalesce(stmt.excluded.address, TruckLocation.address),
                "recorded_at": latest_at,
            },
        )
    )

    if truck is None:
        truck = (
            await db.execute(select(Truck).where(Truck.id == truck_id))
        ).scalar_one_or_none()
    if truck:
        truck.status = status_from_speed(float(latest.speed or 0))
        # A fix is proof the GPS is on, whatever the phone said earlier.
        truck.gps_disabled_at = None
        truck.updated_at = datetime.now(timezone.utc)

    return len(positions)


async def upsert_latest_location(
    db: AsyncSession,
    truck_id,
    latitude: float,
    longitude: float,
    speed: float = 0,
    heading: Optional[float] = None,
    address: Optional[str] = None,
    recorded_at: Optional[datetime] = None,
    truck: Optional[Truck] = None,
) -> None:
    """Single-position convenience wrapper over :func:`record_positions`."""
    await record_positions(
        db,
        truck_id,
        [Position(
            latitude=latitude,
            longitude=longitude,
            speed=speed,
            heading=heading,
            address=address,
            recorded_at=recorded_at,
        )],
        truck=truck,
    )
