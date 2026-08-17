"""Leakage / money-first analytics endpoints."""
from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.deps.auth import get_org_id, require_role
from app.models.enums import UserRole
from app.services.analytics import (
    fuel_anomalies,
    fuel_fraud_events,
    leakage_summary,
    unauthorized_stops,
)

router = APIRouter(prefix="/api/analytics", tags=["Analytics"])

_VIEW = require_role(UserRole.admin, UserRole.manager, UserRole.operator)


class LeakageSummary(BaseModel):
    window_days: int
    estimated_fuel_waste_cost: float
    flagged_trucks: int
    fuel_baseline_l_per_100km: float
    unauthorized_stop_count: int
    total_idle_hours: float
    active_trips: int
    delivered_trips: int


class FuelAnomalyRow(BaseModel):
    truck_id: str
    truck_name: str
    plate_number: str
    distance_km: float
    liters: float
    l_per_100km: float
    baseline_l_per_100km: float
    flagged: bool
    estimated_waste_cost: float


class FuelAnomalies(BaseModel):
    # Echoed back because the service clamps the request to the GPS retention
    # window — the client must know which period the numbers actually describe.
    window_days: int
    baseline_l_per_100km: float
    flagged_count: int
    estimated_waste_cost: float
    trucks: list[FuelAnomalyRow]


class UnauthorizedStop(BaseModel):
    truck_id: str
    truck_name: str
    plate_number: str
    latitude: float
    longitude: float
    started_at: datetime
    ended_at: datetime
    duration_minutes: float


class UnauthorizedStops(BaseModel):
    window_days: int
    unauthorized_stop_count: int
    total_idle_hours: float
    stops: list[UnauthorizedStop]


@router.get("/leakage-summary", response_model=LeakageSummary)
async def get_leakage_summary(
    days: int = Query(default=30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    org: uuid.UUID = Depends(get_org_id),
    _user=Depends(_VIEW),
):
    return LeakageSummary(**await leakage_summary(db, days, org))


@router.get("/fuel-anomalies", response_model=FuelAnomalies)
async def get_fuel_anomalies(
    days: int = Query(default=30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    org: uuid.UUID = Depends(get_org_id),
    _user=Depends(_VIEW),
):
    return FuelAnomalies(**await fuel_anomalies(db, days, org))


@router.get("/unauthorized-stops", response_model=UnauthorizedStops)
async def get_unauthorized_stops(
    days: int = Query(default=30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    org: uuid.UUID = Depends(get_org_id),
    _user=Depends(_VIEW),
):
    return UnauthorizedStops(**await unauthorized_stops(db, days, org))


class FuelFraudEvent(BaseModel):
    fuel_log_id: str
    truck_id: str
    truck_name: str
    plate_number: str
    filled_at: datetime
    liters: float
    cost_per_liter: float
    total_cost: float
    fuel_station: str | None = None
    reasons: list[str]


class FuelFraud(BaseModel):
    window_days: int
    flagged_count: int
    total_suspicious_cost: float
    events: list[FuelFraudEvent]


@router.get("/fuel-fraud", response_model=FuelFraud)
async def get_fuel_fraud(
    days: int = Query(default=30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    org: uuid.UUID = Depends(get_org_id),
    _user=Depends(_VIEW),
):
    """Per-fill suspicious fuel events (oversized fills, price outliers, impossible burn)."""
    return FuelFraud(**await fuel_fraud_events(db, days, org))
