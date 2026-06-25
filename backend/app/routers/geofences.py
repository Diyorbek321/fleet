from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.deps.auth import get_org_id, require_role
from app.models.enums import UserRole
from app.models.geofences import Geofence, GeofenceEvent
from app.models.trucks import Truck
from app.schemas.geofences import (
    GeofenceCreate,
    GeofenceUpdate,
    GeofenceOut,
    GeofenceEventOut,
)

router = APIRouter(prefix="/api/geofences", tags=["Geofences"])

_MANAGE = require_role(UserRole.admin, UserRole.manager, UserRole.operator)


async def _get_owned_fence(db: AsyncSession, geofence_id: uuid.UUID, org: uuid.UUID) -> Geofence:
    fence = (
        await db.execute(select(Geofence).where(Geofence.id == geofence_id, Geofence.org_id == org))
    ).scalar_one_or_none()
    if not fence:
        raise HTTPException(status_code=404, detail="Geofence not found")
    return fence


@router.get("", response_model=list[GeofenceOut])
async def list_geofences(
    active: Optional[bool] = None,
    db: AsyncSession = Depends(get_db),
    org: uuid.UUID = Depends(get_org_id),
):
    stmt = select(Geofence).where(Geofence.org_id == org)
    if active is not None:
        stmt = stmt.where(Geofence.active.is_(active))
    res = await db.execute(stmt.order_by(Geofence.created_at.desc()))
    return res.scalars().all()


@router.post("", response_model=GeofenceOut, status_code=201)
async def create_geofence(
    data: GeofenceCreate,
    db: AsyncSession = Depends(get_db),
    org: uuid.UUID = Depends(get_org_id),
    _user=Depends(_MANAGE),
):
    fence = Geofence(org_id=org, **data.model_dump())
    db.add(fence)
    await db.commit()
    await db.refresh(fence)
    return fence


@router.put("/{geofence_id}", response_model=GeofenceOut)
async def update_geofence(
    geofence_id: uuid.UUID,
    data: GeofenceUpdate,
    db: AsyncSession = Depends(get_db),
    org: uuid.UUID = Depends(get_org_id),
    _user=Depends(_MANAGE),
):
    fence = await _get_owned_fence(db, geofence_id, org)

    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(fence, k, v)
    fence.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(fence)
    return fence


@router.delete("/{geofence_id}", status_code=204)
async def delete_geofence(
    geofence_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    org: uuid.UUID = Depends(get_org_id),
    _user=Depends(_MANAGE),
):
    fence = await _get_owned_fence(db, geofence_id, org)
    await db.delete(fence)
    await db.commit()


@router.get("/events", response_model=list[GeofenceEventOut])
async def list_geofence_events(
    geofence_id: Optional[uuid.UUID] = None,
    truck_id: Optional[uuid.UUID] = None,
    limit: int = Query(default=100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    org: uuid.UUID = Depends(get_org_id),
):
    # Scope events to fences owned by this org (events have no org column of their
    # own, so we join through the geofence).
    stmt = (
        select(GeofenceEvent)
        .join(Geofence, Geofence.id == GeofenceEvent.geofence_id)
        .where(Geofence.org_id == org)
    )
    if geofence_id:
        stmt = stmt.where(GeofenceEvent.geofence_id == geofence_id)
    if truck_id:
        stmt = stmt.where(GeofenceEvent.truck_id == truck_id)
    stmt = stmt.order_by(GeofenceEvent.recorded_at.desc()).limit(limit)
    res = await db.execute(stmt)
    return res.scalars().all()
