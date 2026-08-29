"""What the driver spends on the road: fuel fill-ups and daily cash expenses.

These are the rows the leakage layer reconciles against — a fuel log written
here is what later shows up as a flagged fill-up in the fraud report.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.deps.auth import get_current_driver
from app.models.driver_app import DriverExpense
from app.models.drivers import Driver
from app.models.maintenance import FuelLog
from app.routers.me._common import PREFIX, TAGS, assigned_truck, require_assigned_truck
from app.schemas.maintenance import FuelLogCreate, FuelLogOut
from app.schemas.me import ExpenseCreate, ExpenseOut

router = APIRouter(prefix=PREFIX, tags=TAGS)


# ── Fuel logs ─────────────────────────────────────────────────────────

@router.get("/fuel-logs", response_model=list[FuelLogOut])
async def my_fuel_logs(
    driver: Driver = Depends(get_current_driver),
    db: AsyncSession = Depends(get_db),
    limit: int = 50,
):
    truck = await assigned_truck(db, driver.id)
    if truck is None:
        return []
    res = await db.execute(
        select(FuelLog)
        .where(FuelLog.truck_id == truck.id)
        .order_by(desc(FuelLog.filled_at))
        .limit(min(limit, 200))
    )
    return list(res.scalars().all())


@router.post("/fuel-logs", response_model=FuelLogOut, status_code=status.HTTP_201_CREATED)
async def add_fuel_log(
    data: FuelLogCreate = Body(...),
    driver: Driver = Depends(get_current_driver),
    db: AsyncSession = Depends(get_db),
):
    truck = await require_assigned_truck(db, driver.id)
    total = data.total_cost if data.total_cost is not None else round(data.liters * data.cost_per_liter, 2)
    log = FuelLog(
        truck_id=truck.id,
        liters=data.liters,
        cost_per_liter=data.cost_per_liter,
        total_cost=total,
        mileage_at_fill=data.mileage_at_fill,
        fuel_station=data.fuel_station,
        filled_at=data.filled_at or datetime.now(timezone.utc),
    )
    db.add(log)
    await db.commit()
    await db.refresh(log)
    return log


# ── Daily expenses ────────────────────────────────────────────────────

@router.get("/expenses", response_model=list[ExpenseOut])
async def my_expenses(
    driver: Driver = Depends(get_current_driver),
    db: AsyncSession = Depends(get_db),
    month: Optional[str] = None,
    limit: int = 200,
):
    """My expenses, newest first. Optional ``month`` filter as ``YYYY-MM``."""
    stmt = select(DriverExpense).where(DriverExpense.driver_id == driver.id)
    if month:
        try:
            year_s, mon_s = month.split("-")
            start = date(int(year_s), int(mon_s), 1)
            end = date(start.year + (start.month == 12), (start.month % 12) + 1, 1)
        except (ValueError, IndexError):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="month must be YYYY-MM")
        stmt = stmt.where(DriverExpense.spent_at >= start, DriverExpense.spent_at < end)
    stmt = stmt.order_by(desc(DriverExpense.spent_at), desc(DriverExpense.created_at)).limit(min(limit, 500))
    res = await db.execute(stmt)
    return list(res.scalars().all())


@router.post("/expenses", response_model=ExpenseOut, status_code=status.HTTP_201_CREATED)
async def add_expense(
    data: ExpenseCreate = Body(...),
    driver: Driver = Depends(get_current_driver),
    db: AsyncSession = Depends(get_db),
):
    truck = await assigned_truck(db, driver.id)
    expense = DriverExpense(
        driver_id=driver.id,
        truck_id=truck.id if truck else None,
        category=data.category,
        amount=data.amount,
        note=data.note,
        receipt_url=data.receipt_url,
        spent_at=data.spent_at or datetime.now(timezone.utc).date(),
    )
    db.add(expense)
    await db.commit()
    await db.refresh(expense)
    return expense


@router.delete("/expenses/{expense_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_expense(
    expense_id: uuid.UUID,
    driver: Driver = Depends(get_current_driver),
    db: AsyncSession = Depends(get_db),
):
    res = await db.execute(
        select(DriverExpense).where(
            DriverExpense.id == expense_id, DriverExpense.driver_id == driver.id
        )
    )
    expense = res.scalar_one_or_none()
    if expense is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Expense not found")
    await db.delete(expense)
    await db.commit()
