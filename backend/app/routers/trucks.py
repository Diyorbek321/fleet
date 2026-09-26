from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.deps.auth import get_org_id, require_role
from app.models.enums import TruckStatus, UserRole
from app.models.trucks import Truck, TruckLocation, TruckLocationHistory
from app.schemas.trucks import (
    TruckCreate, TruckUpdate, TruckOut, TruckDetailsOut,
    TruckLocationOut, LocationHistoryItem
)
from app.models.drivers import DriverAssignment, Driver
from app.services import audit

router = APIRouter(prefix="/api/trucks", tags=["Trucks"])

# Anyone signed in can read; only non-driver staff can mutate fleet data.
_MANAGE = require_role(UserRole.admin, UserRole.manager, UserRole.operator)


async def _get_owned_truck(db: AsyncSession, truck_id: uuid.UUID, org: uuid.UUID) -> Truck:
    """Fetch a truck or 404 — scoped to the caller's org so it cannot be used to
    probe or mutate another tenant's trucks."""
    truck = (
        await db.execute(select(Truck).where(Truck.id == truck_id, Truck.org_id == org))
    ).scalar_one_or_none()
    if not truck:
        raise HTTPException(status_code=404, detail="Машина не найдена")
    return truck


@router.get("/locations", response_model=list[TruckLocationOut])
async def list_latest_locations(
    db: AsyncSession = Depends(get_db),
    org: uuid.UUID = Depends(get_org_id),
):
    """Latest known location per truck. Used to seed the live map."""
    res = await db.execute(
        select(TruckLocation).join(Truck, Truck.id == TruckLocation.truck_id).where(Truck.org_id == org)
    )
    return [TruckLocationOut.model_validate(loc) for loc in res.scalars().all()]


@router.get("", response_model=list[TruckOut])
async def list_trucks(
    status: Optional[TruckStatus] = None,
    search: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    org: uuid.UUID = Depends(get_org_id),
):
    stmt = select(Truck).where(Truck.org_id == org)
    if status:
        stmt = stmt.where(Truck.status == status)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(or_(Truck.name.ilike(like), Truck.plate_number.ilike(like), Truck.model.ilike(like)))
    res = await db.execute(stmt.order_by(Truck.created_at.desc()))
    return res.scalars().all()

async def _reject_duplicate_plate(
    db: AsyncSession, org: uuid.UUID, plate: str | None, exclude_id: uuid.UUID | None = None
) -> None:
    """409 if this fleet already runs that plate.

    Scoped to the organization, because that is what the constraint behind it
    now says. An unscoped check would answer "taken" for a plate belonging to a
    different company — a wrong answer, and one that tells the caller something
    about a competitor's fleet.
    """
    if not plate:
        return
    stmt = select(Truck.id).where(Truck.org_id == org, Truck.plate_number == plate)
    if exclude_id is not None:
        stmt = stmt.where(Truck.id != exclude_id)
    if (await db.execute(stmt)).scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=409,
            detail=f"Машина с госномером {plate} уже есть в этом автопарке",
        )


@router.post("", response_model=TruckOut)
async def create_truck(
    data: TruckCreate,
    db: AsyncSession = Depends(get_db),
    org: uuid.UUID = Depends(get_org_id),
    _user=Depends(_MANAGE),
):
    payload = data.model_dump()
    await _reject_duplicate_plate(db, org, payload.get("plate_number"))
    if not (payload.get("name") or "").strip():
        payload["name"] = payload["plate_number"]

    truck = Truck(org_id=org, **payload)
    db.add(truck)
    try:
        await db.commit()
    except IntegrityError:
        # Two operators adding the same plate at once: the check above lost the
        # race, the constraint did not.
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"Машина с госномером {payload.get('plate_number')} уже есть в этом автопарке",
        )
    await db.refresh(truck)
    return truck

@router.get("/{truck_id}", response_model=TruckDetailsOut)
async def get_truck(
    truck_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    org: uuid.UUID = Depends(get_org_id),
):
    res = await db.execute(
        select(Truck)
        .options(selectinload(Truck.location))
        .where(Truck.id == truck_id, Truck.org_id == org)
    )
    truck = res.scalar_one_or_none()
    if not truck:
        raise HTTPException(status_code=404, detail="Машина не найдена")

    # fetch current driver assignment
    da_res = await db.execute(
        select(DriverAssignment, Driver)
        .join(Driver, Driver.id == DriverAssignment.driver_id)
        .where(DriverAssignment.truck_id == truck_id, DriverAssignment.unassigned_at.is_(None))
    )
    row = da_res.first()
    driver = None
    if row:
        _, d = row
        driver = {"id": str(d.id), "name": d.name, "phone": d.phone, "email": d.email}

    return TruckDetailsOut(
        **TruckOut.model_validate(truck).model_dump(),
        location=TruckLocationOut.model_validate(truck.location).model_dump() if truck.location else None,
        driver=driver
    )

@router.put("/{truck_id}", response_model=TruckOut)
async def update_truck(
    truck_id: uuid.UUID,
    data: TruckUpdate,
    db: AsyncSession = Depends(get_db),
    org: uuid.UUID = Depends(get_org_id),
    _user=Depends(_MANAGE),
):
    truck = await _get_owned_truck(db, truck_id, org)

    payload = data.model_dump(exclude_unset=True)
    await _reject_duplicate_plate(db, org, payload.get("plate_number"), exclude_id=truck.id)

    # A truck named after its plate (the default since the form stopped asking
    # for a name) keeps following it when the plate is corrected.
    if (
        payload.get("plate_number")
        and "name" not in payload
        and truck.name == truck.plate_number
    ):
        payload["name"] = payload["plate_number"]

    for k, v in payload.items():
        setattr(truck, k, v)

    truck.updated_at = datetime.now(timezone.utc)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"Машина с госномером {payload.get('plate_number')} уже есть в этом автопарке",
        )
    await db.refresh(truck)
    return truck

@router.delete("/{truck_id}")
async def delete_truck(
    truck_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    org: uuid.UUID = Depends(get_org_id),
    actor=Depends(_MANAGE),
):
    truck = await _get_owned_truck(db, truck_id, org)
    # Cascades through this truck's location history, fuel logs and trips.
    await audit.record_change(
        db,
        actor=actor,
        action=audit.TRUCK_DELETE,
        org_id=org,
        target_type="truck",
        target_id=truck.id,
        target_label=truck.plate_number,
        detail=f"name: {truck.name}",
    )
    await db.delete(truck)
    await db.commit()
    return {"message": "Deleted"}

@router.get("/{truck_id}/location", response_model=TruckLocationOut)
async def get_current_location(
    truck_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    org: uuid.UUID = Depends(get_org_id),
):
    await _get_owned_truck(db, truck_id, org)
    res = await db.execute(select(TruckLocation).where(TruckLocation.truck_id == truck_id))
    loc = res.scalar_one_or_none()
    if not loc:
        raise HTTPException(status_code=404, detail="Местоположение не найдено")
    return TruckLocationOut.model_validate(loc)

@router.get("/{truck_id}/history", response_model=list[LocationHistoryItem])
async def get_location_history(
    truck_id: uuid.UUID,
    start: Optional[datetime] = Query(default=None),
    end: Optional[datetime] = Query(default=None),
    limit: int = Query(default=200, ge=1, le=5000),
    db: AsyncSession = Depends(get_db),
    org: uuid.UUID = Depends(get_org_id),
):
    await _get_owned_truck(db, truck_id, org)
    stmt = select(TruckLocationHistory).where(TruckLocationHistory.truck_id == truck_id)
    if start:
        stmt = stmt.where(TruckLocationHistory.recorded_at >= start)
    if end:
        stmt = stmt.where(TruckLocationHistory.recorded_at <= end)
    stmt = stmt.order_by(TruckLocationHistory.recorded_at.desc()).limit(limit)
    res = await db.execute(stmt)
    return [LocationHistoryItem.model_validate(x) for x in res.scalars().all()]
