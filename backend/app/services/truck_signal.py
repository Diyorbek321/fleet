"""Which trucks are not reporting their position, and the one reason why.

The live map can only draw a truck that has a position. A truck whose driver
never turned sharing on had none, so it was not on the map and nothing said it
was missing — on the Angren TEK pilot a dozen trucks were invisible that way
while the dispatcher assumed the map was complete.

Every enabled truck gets exactly one state, the most actionable first:

* ``no_driver`` — nobody is assigned, so the server refuses any phone's pings
  for it. Fixed in the panel, not on the phone.
* ``gps_off`` — the phone itself reported location services switched off.
* ``never`` — a driver is assigned but no position has ever arrived: the app
  was not installed, not signed in, or sharing was never switched on.
* ``silent`` — positions used to arrive and stopped. Since the app sends a
  heartbeat every few minutes while standing still, this means the phone, the
  app or the network has stopped, not that the truck is parked.
* ``ok`` — reporting.
"""
from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.drivers import Driver, DriverAssignment
from app.models.trucks import Truck, TruckLocation


class SignalState(str, enum.Enum):
    ok = "ok"
    silent = "silent"
    never = "never"
    gps_off = "gps_off"
    no_driver = "no_driver"


@dataclass(frozen=True)
class TruckSignal:
    truck_id: uuid.UUID
    plate_number: str
    name: str
    state: SignalState
    last_fix_at: datetime | None
    gps_disabled_at: datetime | None
    driver_id: uuid.UUID | None
    driver_name: str | None
    driver_phone: str | None
    phone_battery: float | None = None
    phone_tracking: str | None = None
    phone_app_version: str | None = None


def classify(
    *,
    has_driver: bool,
    last_fix_at: datetime | None,
    gps_disabled_at: datetime | None,
    now: datetime,
    stale_after: timedelta,
) -> SignalState:
    """The single most actionable reason a truck is or is not reporting."""
    if not has_driver:
        return SignalState.no_driver
    if gps_disabled_at is not None:
        return SignalState.gps_off
    if last_fix_at is None:
        return SignalState.never
    if now - last_fix_at > stale_after:
        return SignalState.silent
    return SignalState.ok


async def _current_drivers(db: AsyncSession, org_id: uuid.UUID) -> dict[uuid.UUID, Driver]:
    """Each truck's driver: the newest open assignment wins.

    The unique constraint on (truck_id, unassigned_at) does not stop two open
    rows, because NULLs never collide — prod has a truck with two. The newest
    one is the driver the dispatcher most recently put there.
    """
    rows = await db.execute(
        select(DriverAssignment.truck_id, Driver)
        .join(Driver, Driver.id == DriverAssignment.driver_id)
        .join(Truck, Truck.id == DriverAssignment.truck_id)
        .where(Truck.org_id == org_id, DriverAssignment.unassigned_at.is_(None))
        .order_by(DriverAssignment.assigned_at.desc())
    )
    drivers: dict[uuid.UUID, Driver] = {}
    for truck_id, driver in rows.all():
        drivers.setdefault(truck_id, driver)
    return drivers


async def fleet_signal(
    db: AsyncSession,
    org_id: uuid.UUID,
    stale_after: timedelta,
    *,
    now: datetime | None = None,
) -> list[TruckSignal]:
    """Every enabled truck in the organization with its reporting state."""
    now = now or datetime.now(timezone.utc)
    drivers = await _current_drivers(db, org_id)
    rows = await db.execute(
        select(Truck, TruckLocation.recorded_at)
        .outerjoin(TruckLocation, TruckLocation.truck_id == Truck.id)
        .where(Truck.org_id == org_id, Truck.is_enabled.is_(True))
        .order_by(Truck.sort_order.asc().nulls_last(), Truck.created_at.desc())
    )
    result: list[TruckSignal] = []
    for truck, last_fix_at in rows.all():
        driver = drivers.get(truck.id)
        result.append(
            TruckSignal(
                truck_id=truck.id,
                plate_number=truck.plate_number,
                name=truck.name,
                state=classify(
                    has_driver=driver is not None,
                    last_fix_at=last_fix_at,
                    gps_disabled_at=truck.gps_disabled_at,
                    now=now,
                    stale_after=stale_after,
                ),
                last_fix_at=last_fix_at,
                gps_disabled_at=truck.gps_disabled_at,
                driver_id=driver.id if driver else None,
                driver_name=driver.name if driver else None,
                driver_phone=driver.phone if driver else None,
                phone_battery=truck.phone_battery,
                phone_tracking=truck.phone_tracking,
                phone_app_version=truck.phone_app_version,
            )
        )
    return result
