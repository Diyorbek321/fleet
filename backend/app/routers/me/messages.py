"""My inbox: what the dispatcher and the GPS watcher sent me, and my GPS switch."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.deps.auth import get_current_driver
from app.models.driver_messages import DriverMessage
from app.models.drivers import Driver
from app.routers.me._common import PREFIX, TAGS, assigned_truck
from app.schemas.driver_messages import DriverMessageOut, GpsStatusIn

router = APIRouter(prefix=PREFIX, tags=TAGS)


@router.get("/messages", response_model=list[DriverMessageOut])
async def my_messages(
    limit: int = Query(default=50, ge=1, le=200),
    driver: Driver = Depends(get_current_driver),
    db: AsyncSession = Depends(get_db),
):
    rows = await db.execute(
        select(DriverMessage)
        .where(DriverMessage.driver_id == driver.id)
        .order_by(desc(DriverMessage.created_at))
        .limit(limit)
    )
    return rows.scalars().all()


@router.post("/messages/{message_id}/read", response_model=DriverMessageOut)
async def mark_read(
    message_id: uuid.UUID,
    driver: Driver = Depends(get_current_driver),
    db: AsyncSession = Depends(get_db),
):
    message = (
        await db.execute(
            select(DriverMessage).where(
                DriverMessage.id == message_id, DriverMessage.driver_id == driver.id
            )
        )
    ).scalar_one_or_none()
    if message is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Сообщение не найдено")
    if message.read_at is None:
        message.read_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(message)
    return message


@router.post("/gps-status")
async def report_gps_status(
    data: GpsStatusIn = Body(...),
    driver: Driver = Depends(get_current_driver),
    db: AsyncSession = Depends(get_db),
):
    """The app says whether location services are on.

    Only the first "off" is stamped: the app reports on every check, and
    moving the time forward would restart the grace period the GPS watcher
    waits out before telling the dispatcher. A driver with no truck assigned
    is not tracked, so there is nothing to record.
    """
    truck = await assigned_truck(db, driver.id)
    if truck is None:
        return {"message": "no truck"}
    if data.enabled:
        truck.gps_disabled_at = None
    elif truck.gps_disabled_at is None:
        truck.gps_disabled_at = datetime.now(timezone.utc)
    await db.commit()
    return {"message": "ok", "gps_disabled_at": truck.gps_disabled_at}
