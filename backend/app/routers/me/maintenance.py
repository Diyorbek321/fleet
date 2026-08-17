"""Service history the driver can read, and issues they can report."""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, status
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.deps.auth import get_current_driver
from app.models.driver_app import MaintenanceRequest
from app.models.drivers import Driver
from app.models.enums import MaintenanceRequestStatus
from app.models.maintenance import MaintenanceRecord
from app.routers.me._common import PREFIX, TAGS, assigned_truck
from app.schemas.maintenance import MaintenanceRecordOut
from app.schemas.me import MaintenanceRequestCreate, MaintenanceRequestOut

router = APIRouter(prefix=PREFIX, tags=TAGS)


@router.get("/maintenance", response_model=list[MaintenanceRecordOut])
async def my_truck_maintenance(
    driver: Driver = Depends(get_current_driver),
    db: AsyncSession = Depends(get_db),
):
    truck = await assigned_truck(db, driver.id)
    if truck is None:
        return []
    res = await db.execute(
        select(MaintenanceRecord)
        .where(MaintenanceRecord.truck_id == truck.id)
        .order_by(desc(MaintenanceRecord.performed_at))
    )
    return list(res.scalars().all())


@router.get("/maintenance-requests", response_model=list[MaintenanceRequestOut])
async def my_maintenance_requests(
    driver: Driver = Depends(get_current_driver),
    db: AsyncSession = Depends(get_db),
):
    res = await db.execute(
        select(MaintenanceRequest)
        .where(MaintenanceRequest.driver_id == driver.id)
        .order_by(desc(MaintenanceRequest.created_at))
    )
    return list(res.scalars().all())


@router.post("/maintenance-requests", response_model=MaintenanceRequestOut, status_code=status.HTTP_201_CREATED)
async def report_issue(
    data: MaintenanceRequestCreate = Body(...),
    driver: Driver = Depends(get_current_driver),
    db: AsyncSession = Depends(get_db),
):
    truck = await assigned_truck(db, driver.id)
    req = MaintenanceRequest(
        driver_id=driver.id,
        truck_id=truck.id if truck else None,
        title=data.title,
        description=data.description,
        photo_url=data.photo_url,
        status=MaintenanceRequestStatus.open,
    )
    db.add(req)
    await db.commit()
    await db.refresh(req)
    return req
