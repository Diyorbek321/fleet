"""Who I am, what I drive, when I'm on the clock, and where I am."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.ws import ws_manager
from app.deps.auth import get_current_driver, get_current_user
from app.models.driver_app import PushToken, Shift
from app.models.drivers import Driver, SafetyScore
from app.models.enums import ShiftStatus
from app.models.users import User
from app.routers.me._common import PREFIX, TAGS, assigned_truck, require_assigned_truck
from app.schemas.drivers import DriverOut, SafetyScoreOut
from app.schemas.me import (
    AssignedTruckOut,
    LocationPingIn,
    PushTokenIn,
    ShiftEndIn,
    ShiftOut,
    ShiftStartIn,
)
from app.services.gps import upsert_latest_location

router = APIRouter(prefix=PREFIX, tags=TAGS)


# ── Profile & assignment ──────────────────────────────────────────────

@router.get("/profile", response_model=DriverOut)
async def my_profile(driver: Driver = Depends(get_current_driver)):
    return driver


@router.get("/assignment", response_model=Optional[AssignedTruckOut])
async def my_assignment(
    driver: Driver = Depends(get_current_driver),
    db: AsyncSession = Depends(get_db),
):
    """The truck assigned to me right now, or null if none."""
    return await assigned_truck(db, driver.id)


@router.get("/safety-score", response_model=Optional[SafetyScoreOut])
async def my_safety_score(
    driver: Driver = Depends(get_current_driver),
    db: AsyncSession = Depends(get_db),
):
    res = await db.execute(
        select(SafetyScore)
        .where(SafetyScore.driver_id == driver.id)
        .order_by(desc(SafetyScore.calculated_at))
    )
    return res.scalars().first()


# ── Shifts (clock in / out) ───────────────────────────────────────────

@router.get("/shifts/current", response_model=Optional[ShiftOut])
async def current_shift(
    driver: Driver = Depends(get_current_driver),
    db: AsyncSession = Depends(get_db),
):
    res = await db.execute(
        select(Shift)
        .where(Shift.driver_id == driver.id, Shift.status == ShiftStatus.active)
        .order_by(desc(Shift.started_at))
    )
    return res.scalars().first()


@router.post("/shifts/start", response_model=ShiftOut, status_code=status.HTTP_201_CREATED)
async def start_shift(
    data: ShiftStartIn = Body(default_factory=ShiftStartIn),
    driver: Driver = Depends(get_current_driver),
    db: AsyncSession = Depends(get_db),
):
    existing = await db.execute(
        select(Shift).where(Shift.driver_id == driver.id, Shift.status == ShiftStatus.active)
    )
    if existing.scalars().first():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A shift is already active")

    truck = await assigned_truck(db, driver.id)
    shift = Shift(
        driver_id=driver.id,
        truck_id=truck.id if truck else None,
        start_mileage=data.start_mileage,
    )
    db.add(shift)
    await db.commit()
    await db.refresh(shift)
    return shift


@router.post("/shifts/end", response_model=ShiftOut)
async def end_shift(
    data: ShiftEndIn = Body(default_factory=ShiftEndIn),
    driver: Driver = Depends(get_current_driver),
    db: AsyncSession = Depends(get_db),
):
    res = await db.execute(
        select(Shift)
        .where(Shift.driver_id == driver.id, Shift.status == ShiftStatus.active)
        .order_by(desc(Shift.started_at))
    )
    shift = res.scalars().first()
    if shift is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="No active shift")

    shift.status = ShiftStatus.ended
    shift.ended_at = datetime.now(timezone.utc)
    shift.end_mileage = data.end_mileage
    await db.commit()
    await db.refresh(shift)
    return shift


# ── Live location (phone-as-tracker) ──────────────────────────────────

@router.post("/location")
async def ping_location(
    data: LocationPingIn = Body(...),
    driver: Driver = Depends(get_current_driver),
    db: AsyncSession = Depends(get_db),
):
    """Driver's phone streams its GPS position to their assigned truck."""
    truck = await require_assigned_truck(db, driver.id)
    await upsert_latest_location(
        db=db,
        truck_id=truck.id,
        latitude=data.latitude,
        longitude=data.longitude,
        speed=data.speed,
        heading=data.heading,
        recorded_at=data.recorded_at,
    )
    await db.commit()
    # Live map fan-out is scoped to the truck's organization.
    await ws_manager.broadcast_to_org(str(truck.org_id), {
        "type": "truck_location_update",
        "truck_id": str(truck.id),
        "lat": data.latitude,
        "lng": data.longitude,
        "speed": data.speed,
        "heading": data.heading,
        "recorded_at": (data.recorded_at or datetime.now(timezone.utc)).isoformat(),
    })
    return {"message": "ok", "truck_id": str(truck.id)}


# ── Push notification token registration ──────────────────────────────

@router.post("/push-token", status_code=status.HTTP_201_CREATED)
async def register_push_token(
    data: PushTokenIn = Body(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    existing = await db.execute(select(PushToken).where(PushToken.token == data.token))
    row = existing.scalar_one_or_none()
    if row:
        row.user_id = user.id
        row.platform = data.platform
    else:
        db.add(PushToken(user_id=user.id, token=data.token, platform=data.platform))
    await db.commit()
    return {"message": "registered"}
