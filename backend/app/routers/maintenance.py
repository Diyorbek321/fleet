from __future__ import annotations

from datetime import date, timedelta
from typing import Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.database import get_db
from app.deps.auth import get_org_id, require_role
from app.models.maintenance import MaintenanceRecord, FuelLog, ServiceInterval
from app.models.trucks import Truck
from app.models.enums import ServiceStatus, UserRole
from app.schemas.maintenance import (
    MaintenanceRecordCreate, MaintenanceRecordUpdate, MaintenanceRecordOut,
    FuelLogCreate, FuelLogOut, ServiceIntervalOut
)

router = APIRouter(prefix="/api", tags=["Maintenance"])

_MANAGE = require_role(UserRole.admin, UserRole.manager, UserRole.operator)


async def _owned_truck_or_404(db: AsyncSession, truck_id: uuid.UUID, org: uuid.UUID) -> Truck:
    truck = (
        await db.execute(select(Truck).where(Truck.id == truck_id, Truck.org_id == org))
    ).scalar_one_or_none()
    if not truck:
        raise HTTPException(status_code=404, detail="Truck not found")
    return truck


@router.get("/maintenance/reminders", response_model=list[dict])
async def reminders(
    db: AsyncSession = Depends(get_db),
    org: uuid.UUID = Depends(get_org_id),
):
    # due soon computed flag
    today = date.today()
    due_soon_days = 7
    due_soon_km = 500

    res = await db.execute(
        select(ServiceInterval, Truck)
        .join(Truck, Truck.id == ServiceInterval.truck_id)
        .where(Truck.org_id == org)
    )
    out = []
    for si, t in res.all():
        mileage = float(t.mileage) if t else 0.0

        due_soon = False
        if si.status != ServiceStatus.overdue:
            if si.next_service_date and today + timedelta(days=due_soon_days) >= si.next_service_date:
                due_soon = True
            if si.next_service_mileage is not None and mileage + due_soon_km >= float(si.next_service_mileage):
                due_soon = True

        out.append({
            "interval": ServiceIntervalOut.model_validate(si).model_dump(),
            "truck": {"id": str(t.id), "name": t.name, "plate_number": t.plate_number} if t else None,
            "due_soon": due_soon,
        })
    return out

@router.get("/trucks/{truck_id}/maintenance", response_model=list[MaintenanceRecordOut])
async def truck_maintenance_history(
    truck_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    org: uuid.UUID = Depends(get_org_id),
):
    await _owned_truck_or_404(db, truck_id, org)
    res = await db.execute(
        select(MaintenanceRecord)
        .where(MaintenanceRecord.truck_id == truck_id)
        .order_by(MaintenanceRecord.performed_at.desc())
        .limit(limit)
    )
    return [MaintenanceRecordOut.model_validate(x) for x in res.scalars().all()]

@router.post("/trucks/{truck_id}/maintenance", response_model=MaintenanceRecordOut)
async def log_maintenance(
    truck_id: uuid.UUID,
    data: MaintenanceRecordCreate,
    db: AsyncSession = Depends(get_db),
    org: uuid.UUID = Depends(get_org_id),
    _user=Depends(_MANAGE),
):
    await _owned_truck_or_404(db, truck_id, org)

    rec = MaintenanceRecord(truck_id=truck_id, **data.model_dump())
    db.add(rec)
    await db.commit()
    await db.refresh(rec)
    return rec

@router.put("/maintenance/{record_id}", response_model=MaintenanceRecordOut)
async def update_maintenance(
    record_id: uuid.UUID,
    data: MaintenanceRecordUpdate,
    db: AsyncSession = Depends(get_db),
    org: uuid.UUID = Depends(get_org_id),
    _user=Depends(_MANAGE),
):
    rec = (
        await db.execute(
            select(MaintenanceRecord)
            .join(Truck, Truck.id == MaintenanceRecord.truck_id)
            .where(MaintenanceRecord.id == record_id, Truck.org_id == org)
        )
    ).scalar_one_or_none()
    if not rec:
        raise HTTPException(status_code=404, detail="Record not found")

    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(rec, k, v)

    await db.commit()
    await db.refresh(rec)
    return rec

@router.get("/trucks/{truck_id}/fuel-logs", response_model=list[FuelLogOut])
async def truck_fuel_logs(
    truck_id: uuid.UUID,
    limit: int = Query(default=100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    org: uuid.UUID = Depends(get_org_id),
):
    await _owned_truck_or_404(db, truck_id, org)
    res = await db.execute(
        select(FuelLog).where(FuelLog.truck_id == truck_id).order_by(FuelLog.filled_at.desc()).limit(limit)
    )
    return [FuelLogOut.model_validate(x) for x in res.scalars().all()]

@router.post("/trucks/{truck_id}/fuel-logs", response_model=FuelLogOut)
async def add_fuel_log(
    truck_id: uuid.UUID,
    data: FuelLogCreate,
    db: AsyncSession = Depends(get_db),
    org: uuid.UUID = Depends(get_org_id),
    _user=Depends(_MANAGE),
):
    await _owned_truck_or_404(db, truck_id, org)
    # total_cost computed if not provided
    payload = data.model_dump()
    if not payload.get("total_cost"):
        payload["total_cost"] = round(payload["liters"] * payload["cost_per_liter"], 2)

    rec = FuelLog(truck_id=truck_id, **payload)
    db.add(rec)
    await db.commit()
    await db.refresh(rec)
    return rec

@router.get("/maintenance/fuel-summary", response_model=dict)
async def fuel_summary(
    days: int = Query(default=30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    org: uuid.UUID = Depends(get_org_id),
):
    """Fleet-wide fuel cost & MPG over the last N days, scoped to the caller's org.

    Note: backend stores `liters` and `cost_per_liter` columns but for the US
    trucking demo we treat them as gallons and $/gallon. MPG is derived from
    fuel volume and odometer deltas per truck.
    """
    from datetime import datetime, timedelta, timezone
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    res = await db.execute(
        select(FuelLog)
        .join(Truck, Truck.id == FuelLog.truck_id)
        .where(FuelLog.filled_at >= cutoff, Truck.org_id == org)
        .order_by(FuelLog.truck_id, FuelLog.filled_at)
    )
    logs = res.scalars().all()

    total_cost = 0.0
    total_gallons = 0.0
    total_miles = 0.0
    per_truck: dict = {}

    for log in logs:
        tid = str(log.truck_id)
        if tid not in per_truck:
            per_truck[tid] = {"gallons": 0.0, "cost": 0.0, "first_mileage": None, "last_mileage": None}
        bucket = per_truck[tid]
        bucket["gallons"] += float(log.liters)
        bucket["cost"] += float(log.total_cost)
        if log.mileage_at_fill is not None:
            mi = float(log.mileage_at_fill)
            if bucket["first_mileage"] is None or mi < bucket["first_mileage"]:
                bucket["first_mileage"] = mi
            if bucket["last_mileage"] is None or mi > bucket["last_mileage"]:
                bucket["last_mileage"] = mi

        total_cost += float(log.total_cost)
        total_gallons += float(log.liters)

    truck_breakdown = []
    for tid, b in per_truck.items():
        miles = 0.0
        if b["first_mileage"] is not None and b["last_mileage"] is not None:
            miles = max(0.0, b["last_mileage"] - b["first_mileage"])
        total_miles += miles
        mpg = (miles / b["gallons"]) if b["gallons"] > 0 else 0.0
        t_res = await db.execute(select(Truck).where(Truck.id == uuid.UUID(tid)))
        truck = t_res.scalar_one_or_none()
        truck_breakdown.append({
            "truck_id": tid,
            "truck_name": truck.name if truck else "Unknown",
            "plate_number": truck.plate_number if truck else "",
            "gallons": round(b["gallons"], 1),
            "cost": round(b["cost"], 2),
            "miles": round(miles, 0),
            "mpg": round(mpg, 2),
        })
    truck_breakdown.sort(key=lambda x: x["mpg"], reverse=True)

    avg_price = (total_cost / total_gallons) if total_gallons > 0 else 0.0
    fleet_mpg = (total_miles / total_gallons) if total_gallons > 0 else 0.0

    return {
        "days": days,
        "total_cost": round(total_cost, 2),
        "total_gallons": round(total_gallons, 1),
        "total_miles": round(total_miles, 0),
        "fleet_mpg": round(fleet_mpg, 2),
        "avg_price_per_gallon": round(avg_price, 3),
        "trucks": truck_breakdown,
    }


@router.get("/service-intervals", response_model=list[ServiceIntervalOut])
async def list_service_intervals(
    db: AsyncSession = Depends(get_db),
    org: uuid.UUID = Depends(get_org_id),
):
    res = await db.execute(
        select(ServiceInterval)
        .join(Truck, Truck.id == ServiceInterval.truck_id)
        .where(Truck.org_id == org)
    )
    return [ServiceIntervalOut.model_validate(x) for x in res.scalars().all()]


@router.get("/maintenance/recent", response_model=list[MaintenanceRecordOut])
async def recent_maintenance(
    limit: int = Query(default=50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    org: uuid.UUID = Depends(get_org_id),
):
    res = await db.execute(
        select(MaintenanceRecord)
        .join(Truck, Truck.id == MaintenanceRecord.truck_id)
        .where(Truck.org_id == org)
        .order_by(MaintenanceRecord.performed_at.desc())
        .limit(limit)
    )
    return [MaintenanceRecordOut.model_validate(x) for x in res.scalars().all()]


@router.get("/fuel-logs/recent", response_model=list[FuelLogOut])
async def recent_fuel_logs(
    limit: int = Query(default=100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    org: uuid.UUID = Depends(get_org_id),
):
    res = await db.execute(
        select(FuelLog)
        .join(Truck, Truck.id == FuelLog.truck_id)
        .where(Truck.org_id == org)
        .order_by(FuelLog.filled_at.desc())
        .limit(limit)
    )
    return [FuelLogOut.model_validate(x) for x in res.scalars().all()]


@router.get("/maintenance/stats", response_model=dict)
async def maintenance_stats(
    db: AsyncSession = Depends(get_db),
    org: uuid.UUID = Depends(get_org_id),
):
    # Fleet-wide (this org): overdue count, total costs, fuel totals.
    overdue_res = await db.execute(
        select(func.count(ServiceInterval.id))
        .join(Truck, Truck.id == ServiceInterval.truck_id)
        .where(ServiceInterval.status == ServiceStatus.overdue, Truck.org_id == org)
    )
    overdue_count = overdue_res.scalar() or 0

    maint_cost_res = await db.execute(
        select(func.coalesce(func.sum(MaintenanceRecord.cost), 0))
        .join(Truck, Truck.id == MaintenanceRecord.truck_id)
        .where(Truck.org_id == org)
    )
    total_maintenance_cost = float(maint_cost_res.scalar() or 0)

    fuel_cost_res = await db.execute(
        select(func.coalesce(func.sum(FuelLog.total_cost), 0))
        .join(Truck, Truck.id == FuelLog.truck_id)
        .where(Truck.org_id == org)
    )
    total_fuel_cost = float(fuel_cost_res.scalar() or 0)

    fuel_liters_res = await db.execute(
        select(func.coalesce(func.sum(FuelLog.liters), 0))
        .join(Truck, Truck.id == FuelLog.truck_id)
        .where(Truck.org_id == org)
    )
    total_liters = float(fuel_liters_res.scalar() or 0)

    return {
        "overdue_services": int(overdue_count),
        "total_maintenance_cost": total_maintenance_cost,
        "total_fuel_cost": total_fuel_cost,
        "total_fuel_liters": total_liters,
    }
