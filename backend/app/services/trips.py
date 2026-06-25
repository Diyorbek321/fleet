"""Trip helpers: human references and profit-per-trip computation."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.driver_app import DriverExpense
from app.models.maintenance import FuelLog
from app.models.trips import Trip


async def generate_reference(db: AsyncSession) -> str:
    """Sequential human-friendly reference, e.g. TR-2026-000042."""
    year = datetime.now(timezone.utc).year
    prefix = f"TR-{year}-"
    count = (
        await db.execute(
            select(func.count(Trip.id)).where(Trip.reference.like(f"{prefix}%"))
        )
    ).scalar() or 0
    return f"{prefix}{count + 1:06d}"


async def compute_trip_pnl(db: AsyncSession, trip: Trip) -> dict:
    """Revenue minus reconciled fuel + driver expenses for one trip."""
    fuel_cost = (
        await db.execute(
            select(func.coalesce(func.sum(FuelLog.total_cost), 0)).where(FuelLog.trip_id == trip.id)
        )
    ).scalar() or 0
    expense_cost = (
        await db.execute(
            select(func.coalesce(func.sum(DriverExpense.amount), 0)).where(DriverExpense.trip_id == trip.id)
        )
    ).scalar() or 0

    revenue = float(trip.rate or 0)
    fuel_cost = float(fuel_cost)
    expense_cost = float(expense_cost)
    total_cost = fuel_cost + expense_cost
    profit = revenue - total_cost
    margin = (profit / revenue * 100.0) if revenue > 0 else 0.0

    return {
        "trip_id": trip.id,
        "reference": trip.reference,
        "status": trip.status,
        "currency": trip.currency,
        "revenue": round(revenue, 2),
        "fuel_cost": round(fuel_cost, 2),
        "expense_cost": round(expense_cost, 2),
        "total_cost": round(total_cost, 2),
        "profit": round(profit, 2),
        "margin_pct": round(margin, 1),
    }
