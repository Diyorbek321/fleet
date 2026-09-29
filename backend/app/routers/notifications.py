"""The panel's bell: recent owner alerts for my company, and what I have seen."""
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.deps.auth import require_role
from app.models.enums import UserRole
from app.models.panel_notifications import PanelNotification
from app.models.users import User

router = APIRouter(prefix="/api/notifications", tags=["Notifications"])

# Everyone who works in the panel. Drivers have their own inbox in the app.
_PANEL = require_role(UserRole.admin, UserRole.manager, UserRole.operator)


class PanelNotificationOut(BaseModel):
    id: uuid.UUID
    kind: str
    severity: str
    title: str
    body: str
    path: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class NotificationFeedOut(BaseModel):
    items: list[PanelNotificationOut]
    unread_count: int
    seen_at: datetime


def _seen_at(user: User) -> datetime:
    # A new account starts with an empty bell, not with the company's history.
    return user.notifications_seen_at or user.created_at


@router.get("", response_model=NotificationFeedOut)
async def list_notifications(
    limit: int = Query(default=30, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(_PANEL),
):
    """Newest first, plus how many arrived since this user last opened the bell."""
    seen_at = _seen_at(user)
    items = (
        await db.execute(
            select(PanelNotification)
            .where(PanelNotification.org_id == user.org_id)
            .order_by(desc(PanelNotification.created_at))
            .limit(limit)
        )
    ).scalars().all()
    unread = (
        await db.execute(
            select(func.count())
            .select_from(PanelNotification)
            .where(
                PanelNotification.org_id == user.org_id,
                PanelNotification.created_at > seen_at,
            )
        )
    ).scalar_one()
    return NotificationFeedOut(items=items, unread_count=unread, seen_at=seen_at)


@router.post("/seen", response_model=NotificationFeedOut)
async def mark_seen(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(_PANEL),
):
    """Opening the bell reads everything in it."""
    user.notifications_seen_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(user)
    return await list_notifications(limit=30, db=db, user=user)
