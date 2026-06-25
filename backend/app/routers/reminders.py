"""Document & service expiry reminders (dashboard endpoint)."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.deps.auth import get_org_id
from app.services.reminders import DEFAULT_DAYS_AHEAD, upcoming_expiries

router = APIRouter(prefix="/api/reminders", tags=["Reminders"])


@router.get("/expiring", response_model=dict)
async def get_expiring(
    days_ahead: int = Query(default=DEFAULT_DAYS_AHEAD, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    org: uuid.UUID = Depends(get_org_id),
):
    """Driver licences and service intervals expiring/overdue within the window."""
    return await upcoming_expiries(db, org, days_ahead)
