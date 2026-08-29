"""CarGoRuqsat border-queue, driver side (assisted, never automated).

The official booking flow needs ЭЦП/SMS the driver holds, so this app tracks a
booking and hands off into the real site — it never books on their behalf.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.deps.auth import get_current_driver
from app.models.driver_app import QueueWatch
from app.models.drivers import Driver
from app.routers.me._common import PREFIX, TAGS, assigned_truck, require_assigned_truck
from app.schemas.me import (
    QueueHandoffOut,
    QueueRefreshOut,
    QueueStatusOut,
    QueueWatchIn,
    QueueWatchOut,
)
from app.services.cgr import BookingRecord, CgrClient, build_booking_handoff_url, get_cgr_client
from app.services.queue import evaluate_watch, notify_queue_change

router = APIRouter(prefix=PREFIX, tags=TAGS)


def _to_status_out(record: BookingRecord | None) -> QueueStatusOut | None:
    if record is None:
        return None
    return QueueStatusOut(
        plate=record.plate,
        checkpoint=record.checkpoint,
        queue_at=record.queue_at,
        queue_until=record.queue_until,
        status=record.status.value,
        raw_status=record.raw_status,
    )


@router.get("/queue/status", response_model=Optional[QueueStatusOut])
async def queue_status(
    driver: Driver = Depends(get_current_driver),
    db: AsyncSession = Depends(get_db),
    client: CgrClient = Depends(get_cgr_client),
):
    """Live lookup of my assigned truck's booking in the public CarGoRuqsat registry."""
    truck = await require_assigned_truck(db, driver.id)
    record = await client.lookup_truck(truck.plate_number)
    return _to_status_out(record)


@router.get("/queue/handoff", response_model=QueueHandoffOut)
async def queue_handoff(
    driver: Driver = Depends(get_current_driver),
    db: AsyncSession = Depends(get_db),
):
    """Deep link into the official booking flow (driver completes ЭЦП/SMS there)."""
    truck = await assigned_truck(db, driver.id)
    watch = (
        await db.execute(select(QueueWatch).where(QueueWatch.driver_id == driver.id))
    ).scalars().first()
    return QueueHandoffOut(
        url=build_booking_handoff_url(
            checkpoint=watch.checkpoint if watch else None,
            plate=truck.plate_number if truck else None,
        )
    )


@router.get("/queue/watch", response_model=Optional[QueueWatchOut])
async def get_queue_watch(
    driver: Driver = Depends(get_current_driver),
    db: AsyncSession = Depends(get_db),
):
    res = await db.execute(
        select(QueueWatch).where(QueueWatch.driver_id == driver.id, QueueWatch.active.is_(True))
    )
    return res.scalars().first()


@router.put("/queue/watch", response_model=QueueWatchOut)
async def set_queue_watch(
    data: QueueWatchIn = Body(...),
    driver: Driver = Depends(get_current_driver),
    db: AsyncSession = Depends(get_db),
):
    """Start (or update) tracking my truck's queue at a checkpoint."""
    truck = await require_assigned_truck(db, driver.id)
    res = await db.execute(
        select(QueueWatch).where(QueueWatch.driver_id == driver.id, QueueWatch.active.is_(True))
    )
    watch = res.scalars().first()
    if watch is None:
        watch = QueueWatch(driver_id=driver.id, plate=truck.plate_number,
                           checkpoint=data.checkpoint, country=data.country)
        db.add(watch)
    else:
        watch.plate = truck.plate_number
        watch.checkpoint = data.checkpoint
        watch.country = data.country
        watch.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(watch)
    return watch


@router.delete("/queue/watch")
async def stop_queue_watch(
    driver: Driver = Depends(get_current_driver),
    db: AsyncSession = Depends(get_db),
):
    res = await db.execute(
        select(QueueWatch).where(QueueWatch.driver_id == driver.id, QueueWatch.active.is_(True))
    )
    watch = res.scalars().first()
    if watch is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No active watch")
    watch.active = False
    watch.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return {"message": "stopped"}


@router.post("/queue/refresh", response_model=QueueRefreshOut)
async def refresh_queue_watch(
    driver: Driver = Depends(get_current_driver),
    db: AsyncSession = Depends(get_db),
    client: CgrClient = Depends(get_cgr_client),
):
    """Re-check my watch now; notify my devices if the status changed."""
    res = await db.execute(
        select(QueueWatch).where(QueueWatch.driver_id == driver.id, QueueWatch.active.is_(True))
    )
    watch = res.scalars().first()
    if watch is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No active watch")

    record, notify = await evaluate_watch(watch, client)
    if notify:
        await notify_queue_change(db, watch, record)
    await db.commit()
    return QueueRefreshOut(status=_to_status_out(record), changed=notify)
