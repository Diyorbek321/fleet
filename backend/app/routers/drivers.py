from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, update

from app.core.database import get_db
from app.core.security import hash_password
from app.deps.auth import get_org_id, require_role
from app.models.drivers import Driver, DriverAssignment, SafetyScore
from app.models.users import User
from app.models.enums import UserRole
from app.schemas.drivers import (
    DriverCreate, DriverUpdate, DriverOut, AssignDriverIn, SafetyScoreOut,
    CreateDriverLoginIn, DriverLoginOut,
)
from app.models.trucks import Truck

router = APIRouter(prefix="/api/drivers", tags=["Drivers"])

_MANAGE = require_role(UserRole.admin, UserRole.manager, UserRole.operator)


async def _get_owned_driver(db: AsyncSession, driver_id: uuid.UUID, org: uuid.UUID) -> Driver:
    driver = (
        await db.execute(select(Driver).where(Driver.id == driver_id, Driver.org_id == org))
    ).scalar_one_or_none()
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found")
    return driver


@router.post("/{driver_id}/create-login", response_model=DriverLoginOut, status_code=201)
async def create_driver_login(
    driver_id: uuid.UUID,
    data: CreateDriverLoginIn,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_role(UserRole.admin, UserRole.manager)),
):
    """Provision a mobile-app login for a driver (admin/manager only)."""
    driver = await _get_owned_driver(db, driver_id, admin.org_id)

    existing_link = (await db.execute(select(User).where(User.driver_id == driver_id))).scalar_one_or_none()
    if existing_link:
        raise HTTPException(status_code=409, detail="Driver already has a login")

    email_taken = (await db.execute(select(User).where(User.email == data.email))).scalar_one_or_none()
    if email_taken:
        raise HTTPException(status_code=400, detail="Email already registered")

    user = User(
        org_id=admin.org_id,
        email=data.email,
        password_hash=hash_password(data.password),
        role=UserRole.driver,
        driver_id=driver_id,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return DriverLoginOut(user_id=user.id, driver_id=driver_id, email=user.email)

@router.get("", response_model=list[DriverOut])
async def list_drivers(
    status: Optional[str] = None,
    search: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    org: uuid.UUID = Depends(get_org_id),
):
    stmt = select(Driver).where(Driver.org_id == org)
    if status:
        stmt = stmt.where(Driver.status == status)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(or_(Driver.name.ilike(like), Driver.license_number.ilike(like), Driver.email.ilike(like)))
    res = await db.execute(stmt.order_by(Driver.created_at.desc()))
    return res.scalars().all()

@router.post("", response_model=DriverOut)
async def create_driver(
    data: DriverCreate,
    db: AsyncSession = Depends(get_db),
    org: uuid.UUID = Depends(get_org_id),
    _user=Depends(_MANAGE),
):
    driver = Driver(org_id=org, **data.model_dump())
    db.add(driver)
    await db.commit()
    await db.refresh(driver)
    return driver

@router.get("/{driver_id}", response_model=dict)
async def get_driver_details(
    driver_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    org: uuid.UUID = Depends(get_org_id),
):
    driver = await _get_owned_driver(db, driver_id, org)

    # latest safety score
    ss_res = await db.execute(
        select(SafetyScore).where(SafetyScore.driver_id == driver_id).order_by(SafetyScore.period_end.desc()).limit(1)
    )
    ss = ss_res.scalar_one_or_none()

    # current truck assignment (if any)
    da_res = await db.execute(
        select(DriverAssignment).where(DriverAssignment.driver_id == driver_id, DriverAssignment.unassigned_at.is_(None))
    )
    da = da_res.scalar_one_or_none()
    truck = None
    if da:
        t_res = await db.execute(select(Truck).where(Truck.id == da.truck_id))
        t = t_res.scalar_one_or_none()
        if t:
            truck = {"id": str(t.id), "name": t.name, "plate_number": t.plate_number}

    return {
        "driver": DriverOut.model_validate(driver).model_dump(),
        "current_truck": truck,
        "latest_safety_score": SafetyScoreOut.model_validate(ss).model_dump() if ss else None,
    }

@router.put("/{driver_id}", response_model=DriverOut)
async def update_driver(
    driver_id: uuid.UUID,
    data: DriverUpdate,
    db: AsyncSession = Depends(get_db),
    org: uuid.UUID = Depends(get_org_id),
    _user=Depends(_MANAGE),
):
    driver = await _get_owned_driver(db, driver_id, org)

    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(driver, k, v)

    driver.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(driver)
    return driver

@router.delete("/{driver_id}")
async def delete_driver(
    driver_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    org: uuid.UUID = Depends(get_org_id),
    _user=Depends(_MANAGE),
):
    driver = await _get_owned_driver(db, driver_id, org)
    await db.delete(driver)
    await db.commit()
    return {"message": "Deleted"}

@router.post("/{driver_id}/assign")
async def assign_driver_to_truck(
    driver_id: uuid.UUID,
    data: AssignDriverIn,
    db: AsyncSession = Depends(get_db),
    org: uuid.UUID = Depends(get_org_id),
    _user=Depends(_MANAGE),
):
    # ensure driver + truck exist within this org
    await _get_owned_driver(db, driver_id, org)
    t_res = await db.execute(select(Truck).where(Truck.id == data.truck_id, Truck.org_id == org))
    if not t_res.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Truck not found")

    # unassign current active assignment for this truck (if any)
    da_truck_res = await db.execute(
        select(DriverAssignment).where(DriverAssignment.truck_id == data.truck_id, DriverAssignment.unassigned_at.is_(None))
    )
    da_truck = da_truck_res.scalar_one_or_none()
    if da_truck:
        da_truck.unassigned_at = datetime.now(timezone.utc)

    # unassign current active assignment for this driver (if any)
    da_driver_res = await db.execute(
        select(DriverAssignment).where(DriverAssignment.driver_id == driver_id, DriverAssignment.unassigned_at.is_(None))
    )
    da_driver = da_driver_res.scalar_one_or_none()
    if da_driver:
        da_driver.unassigned_at = datetime.now(timezone.utc)

    # create new assignment
    assign = DriverAssignment(driver_id=driver_id, truck_id=data.truck_id)
    db.add(assign)
    await db.commit()
    return {"message": "Assigned", "assignment_id": str(assign.id)}

@router.post("/{driver_id}/unassign")
async def unassign_driver(
    driver_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    org: uuid.UUID = Depends(get_org_id),
    _user=Depends(_MANAGE),
):
    await _get_owned_driver(db, driver_id, org)
    da_res = await db.execute(
        select(DriverAssignment).where(DriverAssignment.driver_id == driver_id, DriverAssignment.unassigned_at.is_(None))
    )
    da = da_res.scalar_one_or_none()
    if not da:
        raise HTTPException(status_code=404, detail="No active assignment")
    da.unassigned_at = datetime.now(timezone.utc)
    await db.commit()
    return {"message": "Unassigned"}

@router.get("/{driver_id}/safety-scores", response_model=list[SafetyScoreOut])
async def get_safety_scores(
    driver_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    org: uuid.UUID = Depends(get_org_id),
):
    await _get_owned_driver(db, driver_id, org)
    res = await db.execute(
        select(SafetyScore).where(SafetyScore.driver_id == driver_id).order_by(SafetyScore.period_end.desc()).limit(limit)
    )
    return [SafetyScoreOut.model_validate(x) for x in res.scalars().all()]
