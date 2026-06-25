"""Admin/manager views of data drivers submit from the mobile app.

The driver app writes maintenance requests, expenses, and shifts via the
self-scoped ``/api/me`` endpoints. These admin endpoints let the web platform
read that data back fleet-wide (and act on maintenance requests), closing the
gap where driver submissions were invisible to owners.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.deps.auth import require_role
from app.models.driver_app import MaintenanceRequest, DriverExpense, Shift
from app.models.drivers import Driver
from app.models.trucks import Truck
from app.models.enums import UserRole, MaintenanceRequestStatus
from app.schemas.admin_driver_data import (
    MaintenanceRequestAdminOut,
    UpdateMaintenanceRequestStatusIn,
    ExpenseAdminOut,
    ShiftAdminOut,
)

router = APIRouter(prefix="/api", tags=["Driver Data (admin)"])

# Both admins and managers may view/act on driver-submitted data.
_staff = require_role(UserRole.admin, UserRole.manager)


# ── Maintenance requests (fleet-wide queue) ──────────────────────────────

@router.get("/maintenance-requests", response_model=list[MaintenanceRequestAdminOut])
async def list_maintenance_requests(
    status: Optional[MaintenanceRequestStatus] = Query(default=None),
    db: AsyncSession = Depends(get_db),
    user=Depends(_staff),
):
    """Issue reports raised by drivers, newest first. Optional status filter.

    Scoped to the staff member's organization by joining through the reporting
    driver (requests always carry a driver at creation time).
    """
    stmt = (
        select(MaintenanceRequest, Driver.name, Truck.plate_number)
        .join(Driver, Driver.id == MaintenanceRequest.driver_id)
        .outerjoin(Truck, Truck.id == MaintenanceRequest.truck_id)
        .where(Driver.org_id == user.org_id)
        .order_by(MaintenanceRequest.created_at.desc())
    )
    if status is not None:
        stmt = stmt.where(MaintenanceRequest.status == status)

    rows = (await db.execute(stmt)).all()
    return [
        MaintenanceRequestAdminOut(
            id=mr.id,
            driver_id=mr.driver_id,
            driver_name=driver_name,
            truck_id=mr.truck_id,
            truck_plate=truck_plate,
            title=mr.title,
            description=mr.description,
            photo_url=mr.photo_url,
            status=mr.status,
            created_at=mr.created_at,
        )
        for mr, driver_name, truck_plate in rows
    ]


@router.put("/maintenance-requests/{request_id}/status", response_model=MaintenanceRequestAdminOut)
async def update_maintenance_request_status(
    request_id: uuid.UUID,
    data: UpdateMaintenanceRequestStatusIn,
    db: AsyncSession = Depends(get_db),
    user=Depends(_staff),
):
    """Move a request through open → acknowledged → resolved."""
    req = (
        await db.execute(
            select(MaintenanceRequest)
            .join(Driver, Driver.id == MaintenanceRequest.driver_id)
            .where(MaintenanceRequest.id == request_id, Driver.org_id == user.org_id)
        )
    ).scalar_one_or_none()
    if req is None:
        raise HTTPException(status_code=404, detail="Maintenance request not found")

    req.status = data.status
    await db.commit()
    await db.refresh(req)

    driver_name = None
    if req.driver_id:
        driver_name = (
            await db.execute(select(Driver.name).where(Driver.id == req.driver_id))
        ).scalar_one_or_none()
    truck_plate = None
    if req.truck_id:
        truck_plate = (
            await db.execute(select(Truck.plate_number).where(Truck.id == req.truck_id))
        ).scalar_one_or_none()

    return MaintenanceRequestAdminOut(
        id=req.id,
        driver_id=req.driver_id,
        driver_name=driver_name,
        truck_id=req.truck_id,
        truck_plate=truck_plate,
        title=req.title,
        description=req.description,
        photo_url=req.photo_url,
        status=req.status,
        created_at=req.created_at,
    )


# ── Per-driver expenses (individual line items + receipts) ────────────────

@router.get("/drivers/{driver_id}/expenses", response_model=list[ExpenseAdminOut])
async def list_driver_expenses(
    driver_id: uuid.UUID,
    month: Optional[str] = Query(default=None, description="YYYY-MM filter on spent_at"),
    db: AsyncSession = Depends(get_db),
    user=Depends(_staff),
):
    """Individual expenses a driver logged, newest first (with receipt URLs)."""
    driver = (
        await db.execute(select(Driver.id).where(Driver.id == driver_id, Driver.org_id == user.org_id))
    ).scalar_one_or_none()
    if driver is None:
        raise HTTPException(status_code=404, detail="Driver not found")

    stmt = (
        select(DriverExpense, Truck.plate_number)
        .outerjoin(Truck, Truck.id == DriverExpense.truck_id)
        .where(DriverExpense.driver_id == driver_id)
        .order_by(DriverExpense.spent_at.desc(), DriverExpense.created_at.desc())
    )
    if month:
        try:
            year_s, mon_s = month.split("-")
            start = date(int(year_s), int(mon_s), 1)
            end = date(int(year_s) + (1 if int(mon_s) == 12 else 0), (int(mon_s) % 12) + 1, 1)
        except (ValueError, IndexError):
            raise HTTPException(status_code=400, detail="month must be YYYY-MM")
        stmt = stmt.where(DriverExpense.spent_at >= start, DriverExpense.spent_at < end)

    rows = (await db.execute(stmt)).all()
    return [
        ExpenseAdminOut(
            id=e.id,
            driver_id=e.driver_id,
            truck_id=e.truck_id,
            truck_plate=truck_plate,
            category=e.category,
            amount=float(e.amount),
            note=e.note,
            receipt_url=e.receipt_url,
            spent_at=e.spent_at,
            created_at=e.created_at,
        )
        for e, truck_plate in rows
    ]


# ── Per-driver shifts ─────────────────────────────────────────────────────

@router.get("/drivers/{driver_id}/shifts", response_model=list[ShiftAdminOut])
async def list_driver_shifts(
    driver_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    user=Depends(_staff),
):
    """A driver's clock-in/out history, newest first."""
    driver = (
        await db.execute(select(Driver.id).where(Driver.id == driver_id, Driver.org_id == user.org_id))
    ).scalar_one_or_none()
    if driver is None:
        raise HTTPException(status_code=404, detail="Driver not found")

    stmt = (
        select(Shift, Truck.plate_number)
        .outerjoin(Truck, Truck.id == Shift.truck_id)
        .where(Shift.driver_id == driver_id)
        .order_by(Shift.started_at.desc())
        .limit(limit)
    )
    rows = (await db.execute(stmt)).all()
    return [
        ShiftAdminOut(
            id=s.id,
            driver_id=s.driver_id,
            truck_id=s.truck_id,
            truck_plate=truck_plate,
            status=s.status,
            started_at=s.started_at,
            ended_at=s.ended_at,
            start_mileage=float(s.start_mileage) if s.start_mileage is not None else None,
            end_mileage=float(s.end_mileage) if s.end_mileage is not None else None,
        )
        for s, truck_plate in rows
    ]
