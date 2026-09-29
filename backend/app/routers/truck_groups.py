"""Link a truck to its Telegram group, see which group it is, unlink it.

The group itself is chosen in Telegram: the panel hands out a ``startgroup``
link, and the webhook binds whichever group the bot is added to with it (see
``app.services.trip_orders.activate_truck_group``). The chat id never passes
through here.
"""
import uuid
from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.deps.auth import require_role
from app.models.enums import UserRole
from app.models.truck_groups import TruckTelegramGroup
from app.models.trucks import Truck
from app.models.users import User
from app.services.trip_orders import build_group_deep_link, mint_group_token

router = APIRouter(prefix="/api/trucks", tags=["Truck Telegram groups"])

_MANAGE = require_role(UserRole.admin, UserRole.manager, UserRole.operator)


class TruckGroupOut(BaseModel):
    # none: never linked. pending: link made, bot not yet added.
    # linked: posting to a group. lost: the bot was removed from the group.
    status: Literal["none", "pending", "linked", "lost"]
    chat_title: Optional[str] = None
    activated_at: Optional[datetime] = None
    # Only while pending: once the bot is in a group the link is spent.
    deep_link: Optional[str] = None


def _out(row: TruckTelegramGroup | None) -> TruckGroupOut:
    if row is None:
        return TruckGroupOut(status="none")
    if row.chat_id:
        return TruckGroupOut(status="linked", chat_title=row.chat_title, activated_at=row.activated_at)
    if row.activated_at:
        return TruckGroupOut(status="lost", chat_title=row.chat_title, activated_at=row.activated_at)
    return TruckGroupOut(status="pending", deep_link=build_group_deep_link(row.token))


async def _owned_truck(db: AsyncSession, truck_id: uuid.UUID, org_id: uuid.UUID) -> Truck:
    truck = (
        await db.execute(select(Truck).where(Truck.id == truck_id, Truck.org_id == org_id))
    ).scalar_one_or_none()
    if truck is None:
        raise HTTPException(status_code=404, detail="Машина не найдена")
    return truck


async def _row(db: AsyncSession, truck_id: uuid.UUID) -> TruckTelegramGroup | None:
    return (
        await db.execute(select(TruckTelegramGroup).where(TruckTelegramGroup.truck_id == truck_id))
    ).scalar_one_or_none()


@router.get("/{truck_id}/telegram-group", response_model=TruckGroupOut)
async def get_truck_group(
    truck_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(_MANAGE),
):
    await _owned_truck(db, truck_id, user.org_id)
    return _out(await _row(db, truck_id))


@router.post("/{truck_id}/telegram-group", response_model=TruckGroupOut)
async def link_truck_group(
    truck_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(_MANAGE),
):
    """A fresh link. Any group already linked is let go: one group per truck."""
    await _owned_truck(db, truck_id, user.org_id)
    row = await _row(db, truck_id)
    if row is None:
        row = TruckTelegramGroup(org_id=user.org_id, truck_id=truck_id, token=mint_group_token())
        db.add(row)
    else:
        row.token = mint_group_token()
        row.chat_id = None
        row.chat_title = None
        row.activated_at = None
    await db.commit()
    return _out(row)


@router.delete("/{truck_id}/telegram-group", response_model=TruckGroupOut)
async def unlink_truck_group(
    truck_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(_MANAGE),
):
    await _owned_truck(db, truck_id, user.org_id)
    await db.execute(delete(TruckTelegramGroup).where(TruckTelegramGroup.truck_id == truck_id))
    await db.commit()
    return _out(None)
