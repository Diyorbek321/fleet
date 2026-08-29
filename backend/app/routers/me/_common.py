"""Shared plumbing for the ``/api/me`` sub-routers.

Every endpoint under ``/api/me`` resolves the caller through
``get_current_driver`` and then works from *their* assignment, so the
truck-lookup and trip-ownership helpers below are the choke points that keep a
driver inside their own data. They live here rather than being duplicated per
module so there is exactly one definition of "my truck" and "my trip".
"""
from __future__ import annotations

import uuid
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.drivers import Driver, DriverAssignment
from app.models.enums import TripStatus
from app.models.trips import Trip
from app.models.trucks import Truck

# Shared by every sub-router so the mounted paths and the OpenAPI grouping stay
# identical to when this was one module.
PREFIX = "/api/me"
TAGS = ["Driver App"]


async def active_assignment(db: AsyncSession, driver_id: uuid.UUID) -> Optional[DriverAssignment]:
    res = await db.execute(
        select(DriverAssignment)
        .where(DriverAssignment.driver_id == driver_id, DriverAssignment.unassigned_at.is_(None))
        .order_by(desc(DriverAssignment.assigned_at))
    )
    return res.scalars().first()


async def assigned_truck(db: AsyncSession, driver_id: uuid.UUID) -> Optional[Truck]:
    assignment = await active_assignment(db, driver_id)
    if assignment is None:
        return None
    res = await db.execute(select(Truck).where(Truck.id == assignment.truck_id))
    return res.scalar_one_or_none()


async def require_assigned_truck(db: AsyncSession, driver_id: uuid.UUID) -> Truck:
    truck = await assigned_truck(db, driver_id)
    if truck is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="No truck currently assigned")
    return truck


async def active_trip(db: AsyncSession, driver_id: uuid.UUID) -> Optional[Trip]:
    """The trip this driver is currently running, if any.

    Used to attach a fuel fill or an expense to the load it was spent on.
    Without that link the cost exists but belongs to nothing: ``compute_trip_pnl``
    sums ``FuelLog.trip_id == trip.id``, so an unlinked fill leaves the trip
    reporting zero fuel cost and a margin near 100%. For freight, where fuel is
    the largest single cost, that is not a rounding error — it is the whole
    answer.

    "Currently running" is this driver's newest trip that has been neither
    delivered nor cancelled. A driver runs one load at a time, so newest is
    unambiguous in practice. If they have none open the cost is still recorded,
    just without a trip: the money did leave, and refusing to record it would
    lose the fact entirely.
    """
    res = await db.execute(
        select(Trip)
        .where(
            Trip.driver_id == driver_id,
            Trip.status.notin_((TripStatus.delivered, TripStatus.cancelled)),
        )
        .order_by(desc(Trip.created_at))
    )
    return res.scalars().first()


async def own_trip_or_404(db: AsyncSession, trip_id: uuid.UUID, driver: Driver) -> Trip:
    """Fetch a trip and assert it is assigned to the signed-in driver.

    404 rather than 403 for someone else's trip: a driver must not be able to
    probe which trip ids exist.
    """
    res = await db.execute(select(Trip).where(Trip.id == trip_id))
    trip = res.scalar_one_or_none()
    if trip is None or trip.driver_id != driver.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trip not found")
    return trip
