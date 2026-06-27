"""Trips / freight orders — CRUD, status timeline, and per-trip P&L."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.database import get_db
from app.deps.auth import get_current_user, get_org_id, require_role
from app.models.drivers import Driver
from app.models.enums import TripEventType, TripStatus, UserRole
from app.models.trips import Trip, TripDocument, TripEvent, TripSegment
from app.models.trucks import Truck
from app.schemas.trips import (
    TripAdvance,
    TripCreate,
    TripDetailsOut,
    TripDocumentOut,
    TripOut,
    TripPnL,
    TripSegmentOut,
    TripUpdate,
)
from app.services.storage import delete_object, is_configured, presigned_get_url
from app.services.trip_segments import segment_trip
from app.services.trips import compute_trip_pnl, generate_reference

router = APIRouter(prefix="/api/trips", tags=["Trips"])

_MANAGE = require_role(UserRole.admin, UserRole.manager, UserRole.operator)

# Timestamps stamped automatically on first entry into a status.
_START_STATUSES = {TripStatus.en_route, TripStatus.loading}


async def _get_owned_trip(db: AsyncSession, trip_id: uuid.UUID, org: uuid.UUID, *, with_events: bool = False) -> Trip:
    stmt = select(Trip).where(Trip.id == trip_id, Trip.org_id == org)
    if with_events:
        stmt = stmt.options(selectinload(Trip.events))
    trip = (await db.execute(stmt)).scalar_one_or_none()
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")
    return trip


async def _detail(db: AsyncSession, trip: Trip) -> TripDetailsOut:
    truck_name = truck_plate = driver_name = None
    if trip.truck_id:
        t = (await db.execute(select(Truck).where(Truck.id == trip.truck_id))).scalar_one_or_none()
        if t:
            truck_name, truck_plate = t.name, t.plate_number
    if trip.driver_id:
        d = (await db.execute(select(Driver).where(Driver.id == trip.driver_id))).scalar_one_or_none()
        if d:
            driver_name = d.name
    base = TripOut.model_validate(trip).model_dump()
    return TripDetailsOut(
        **base,
        events=[e for e in trip.events],
        truck_name=truck_name,
        truck_plate=truck_plate,
        driver_name=driver_name,
    )


@router.get("", response_model=list[TripOut])
async def list_trips(
    status: Optional[TripStatus] = None,
    truck_id: Optional[uuid.UUID] = None,
    driver_id: Optional[uuid.UUID] = None,
    db: AsyncSession = Depends(get_db),
    org: uuid.UUID = Depends(get_org_id),
):
    stmt = select(Trip).where(Trip.org_id == org)
    if status:
        stmt = stmt.where(Trip.status == status)
    if truck_id:
        stmt = stmt.where(Trip.truck_id == truck_id)
    if driver_id:
        stmt = stmt.where(Trip.driver_id == driver_id)
    res = await db.execute(stmt.order_by(Trip.created_at.desc()))
    return res.scalars().all()


@router.post("", response_model=TripDetailsOut)
async def create_trip(
    data: TripCreate,
    db: AsyncSession = Depends(get_db),
    org: uuid.UUID = Depends(get_org_id),
    _user=Depends(_MANAGE),
):
    payload = data.model_dump(exclude_unset=True)
    reference = payload.pop("reference", None) or await generate_reference(db)

    existing = (await db.execute(select(Trip).where(Trip.reference == reference))).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="Trip reference already exists")

    # A trip may only reference a truck/driver from the same organization.
    if payload.get("truck_id") is not None:
        owned = (await db.execute(select(Truck.id).where(Truck.id == payload["truck_id"], Truck.org_id == org))).scalar_one_or_none()
        if not owned:
            raise HTTPException(status_code=404, detail="Truck not found")
    if payload.get("driver_id") is not None:
        owned = (await db.execute(select(Driver.id).where(Driver.id == payload["driver_id"], Driver.org_id == org))).scalar_one_or_none()
        if not owned:
            raise HTTPException(status_code=404, detail="Driver not found")

    trip = Trip(org_id=org, reference=reference, **payload)
    db.add(trip)
    await db.flush()
    db.add(TripEvent(trip_id=trip.id, event=TripEventType.created, to_status=trip.status))
    await db.commit()

    res = await db.execute(select(Trip).options(selectinload(Trip.events)).where(Trip.id == trip.id))
    return await _detail(db, res.scalar_one())


@router.get("/{trip_id}", response_model=TripDetailsOut)
async def get_trip(
    trip_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    org: uuid.UUID = Depends(get_org_id),
):
    trip = await _get_owned_trip(db, trip_id, org, with_events=True)
    return await _detail(db, trip)


@router.put("/{trip_id}", response_model=TripDetailsOut)
async def update_trip(
    trip_id: uuid.UUID,
    data: TripUpdate,
    db: AsyncSession = Depends(get_db),
    org: uuid.UUID = Depends(get_org_id),
    _user=Depends(_MANAGE),
):
    trip = await _get_owned_trip(db, trip_id, org, with_events=True)
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(trip, k, v)
    trip.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(trip)
    res = await db.execute(select(Trip).options(selectinload(Trip.events)).where(Trip.id == trip.id))
    return await _detail(db, res.scalar_one())


@router.post("/{trip_id}/advance", response_model=TripDetailsOut)
async def advance_trip(
    trip_id: uuid.UUID,
    data: TripAdvance,
    db: AsyncSession = Depends(get_db),
    org: uuid.UUID = Depends(get_org_id),
    _user=Depends(_MANAGE),
):
    """Transition a trip to a new status and append a timeline event."""
    trip = await _get_owned_trip(db, trip_id, org)

    from_status = trip.status
    now = datetime.now(timezone.utc)

    if data.to_status in _START_STATUSES and trip.started_at is None:
        trip.started_at = now
    if data.to_status == TripStatus.delivered:
        trip.delivered_at = now

    trip.status = data.to_status
    trip.updated_at = now

    event_type = TripEventType.status_change
    if data.to_status == TripStatus.at_border:
        event_type = TripEventType.border_arrival
    elif data.to_status == TripStatus.delivered:
        event_type = TripEventType.pod

    db.add(
        TripEvent(
            trip_id=trip.id,
            event=event_type,
            from_status=from_status,
            to_status=data.to_status,
            note=data.note,
            latitude=data.latitude,
            longitude=data.longitude,
            recorded_at=now,
        )
    )
    await db.commit()
    res = await db.execute(select(Trip).options(selectinload(Trip.events)).where(Trip.id == trip.id))
    return await _detail(db, res.scalar_one())


@router.get("/{trip_id}/pnl", response_model=TripPnL)
async def trip_pnl(
    trip_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    org: uuid.UUID = Depends(get_org_id),
):
    trip = await _get_owned_trip(db, trip_id, org)
    return TripPnL(**await compute_trip_pnl(db, trip))


@router.get("/{trip_id}/segments", response_model=list[TripSegmentOut])
async def get_trip_segments(
    trip_id: uuid.UUID,
    recompute: bool = Query(default=False, description="Recompute from GPS history before returning"),
    db: AsyncSession = Depends(get_db),
    org: uuid.UUID = Depends(get_org_id),
):
    """Return the trip's moving/stopped segments.

    By default returns the stored segments; pass ``recompute=true`` to rebuild
    them from the truck's GPS history first.
    """
    trip = await _get_owned_trip(db, trip_id, org)

    if recompute:
        return await segment_trip(db, trip)

    res = await db.execute(
        select(TripSegment).where(TripSegment.trip_id == trip_id).order_by(TripSegment.seq)
    )
    return res.scalars().all()


@router.post("/{trip_id}/segments", response_model=list[TripSegmentOut])
async def recompute_trip_segments(
    trip_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    org: uuid.UUID = Depends(get_org_id),
    _user=Depends(_MANAGE),
):
    """Recompute a trip's segments from its truck's GPS history and store them."""
    trip = await _get_owned_trip(db, trip_id, org)
    return await segment_trip(db, trip)


@router.get("/{trip_id}/documents", response_model=list[TripDocumentOut])
async def list_trip_documents(
    trip_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    org: uuid.UUID = Depends(get_org_id),
    _user=Depends(_MANAGE),
):
    """All documents uploaded for this trip, newest first (presigned URLs).

    Strictly per-trip and org-scoped via ``_get_owned_trip``.
    """
    trip = await _get_owned_trip(db, trip_id, org)
    if not is_configured():
        raise HTTPException(status_code=503, detail="Document storage is not configured")

    res = await db.execute(
        select(TripDocument)
        .where(TripDocument.trip_id == trip.id)
        .order_by(TripDocument.uploaded_at.desc())
    )
    docs = res.scalars().all()

    # Resolve driver names in one query for the dispatcher view.
    driver_ids = {d.driver_id for d in docs if d.driver_id is not None}
    driver_names: dict[uuid.UUID, str] = {}
    if driver_ids:
        rows = (await db.execute(select(Driver.id, Driver.name).where(Driver.id.in_(driver_ids)))).all()
        driver_names = {row[0]: row[1] for row in rows}

    return [
        TripDocumentOut(
            id=d.id,
            trip_id=d.trip_id,
            category=d.category,
            caption=d.caption,
            content_type=d.content_type,
            size_bytes=d.size_bytes,
            url=presigned_get_url(d.storage_key),
            uploaded_at=d.uploaded_at,
            driver_name=driver_names.get(d.driver_id) if d.driver_id else None,
        )
        for d in docs
    ]


@router.delete("/{trip_id}/documents/{doc_id}")
async def delete_trip_document(
    trip_id: uuid.UUID,
    doc_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    org: uuid.UUID = Depends(get_org_id),
    _user=Depends(require_role(UserRole.admin, UserRole.manager)),
):
    """Delete a trip document — removes it from object storage then the DB row."""
    trip = await _get_owned_trip(db, trip_id, org)
    res = await db.execute(
        select(TripDocument).where(
            TripDocument.id == doc_id, TripDocument.trip_id == trip.id
        )
    )
    doc = res.scalar_one_or_none()
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")

    if is_configured():
        delete_object(doc.storage_key)
    await db.delete(doc)
    await db.commit()
    return {"message": "Deleted"}


@router.delete("/{trip_id}")
async def delete_trip(
    trip_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    org: uuid.UUID = Depends(get_org_id),
    _user=Depends(require_role(UserRole.admin, UserRole.manager)),
):
    trip = await _get_owned_trip(db, trip_id, org)
    await db.delete(trip)
    await db.commit()
    return {"message": "Deleted"}
