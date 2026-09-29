"""Dispatcher → driver messages: send one, and see what was sent.

Mounted under ``/api/drivers/{driver_id}`` because the recipient is a person,
not a truck: a driver who swaps trucks keeps their inbox.
"""
import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rate_limit import limiter
from app.deps.auth import require_role
from app.models.driver_messages import DriverMessage, DriverMessageKind
from app.models.enums import UserRole
from app.models.users import User
from app.routers.drivers import _get_owned_driver
from app.routers.me._common import assigned_truck
from app.schemas.driver_messages import DriverMessageIn, DriverMessageOut
from app.services.driver_messages import send_driver_message

router = APIRouter(prefix="/api/drivers", tags=["Driver messages"])

_MANAGE = require_role(UserRole.admin, UserRole.manager, UserRole.operator)

DEFAULT_TITLE = "Сообщение от диспетчера"


@router.post("/{driver_id}/messages", response_model=DriverMessageOut, status_code=201)
@limiter.limit("30/minute")
async def send_message(
    request: Request,  # noqa: ARG001 — slowapi reads the client address off it
    driver_id: uuid.UUID,
    data: DriverMessageIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(_MANAGE),
):
    """Send a message to the driver's phone and inbox.

    ``devices_delivered == 0`` in the answer means no phone took the push —
    the driver has no app login, or never allowed notifications. The message
    is still in their inbox for the next time they open the app.
    """
    driver = await _get_owned_driver(db, driver_id, user.org_id)
    truck = await assigned_truck(db, driver.id)
    message = await send_driver_message(
        db,
        org_id=user.org_id,
        driver_id=driver.id,
        truck_id=truck.id if truck else None,
        kind=DriverMessageKind.dispatcher,
        title=data.title or DEFAULT_TITLE,
        body=data.body,
        sent_by_user_id=user.id,
    )
    return message


@router.get("/{driver_id}/messages", response_model=list[DriverMessageOut])
async def list_messages(
    driver_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(_MANAGE),
):
    """Newest first: what was sent to this driver, and whether they read it."""
    await _get_owned_driver(db, driver_id, user.org_id)
    rows = await db.execute(
        select(DriverMessage)
        .where(DriverMessage.driver_id == driver_id, DriverMessage.org_id == user.org_id)
        .order_by(desc(DriverMessage.created_at))
        .limit(limit)
    )
    return rows.scalars().all()
