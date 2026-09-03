"""Settings a company keeps for itself, as opposed to the ones the platform
operator keeps about it.

Today that is exchange rates. A cross-border trip is paid for in three
currencies, and the country-expense report cannot put Kazakh tenge next to
Russian roubles without one. Trips that recorded their own exchange bring their
own rate and never touch these; these cover the rest — the Uzbek leg always,
since a driver leaves home with so'm already in hand and no exchange is written
down for it.

Deliberately not in ``/api/organizations``: that router is the platform
operator's console over *other* people's tenants and its payloads carry
operator-only fields such as ``notes``. This one is a company editing its own
row, so it exposes those three numbers and nothing else.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.deps.auth import get_current_user, get_org_id, require_role
from app.models.enums import UserRole
from app.models.organizations import Organization
from app.models.users import User

router = APIRouter(prefix="/api/org", tags=["Organization settings"])


class OrgSettingsOut(BaseModel):
    """How many units of each currency one US dollar buys.

    ``None`` means unset, and the report says so rather than converting at a
    rate nobody chose — see ``app.services.country_expenses``.
    """

    usd_to_kzt: float | None = None
    usd_to_rub: float | None = None
    usd_to_uzs: float | None = None
    updated_at: datetime | None = None

    class Config:
        from_attributes = True


class OrgSettingsIn(BaseModel):
    """A full replacement of the three rates.

    Not a partial update: ``null`` is a meaningful value here (clear the rate,
    go back to showing native amounts only), and a PATCH that treats missing
    and null alike gives no way to express it.
    """

    # A rate of zero or below is not a rate; rejecting it here keeps a division
    # by zero out of every consumer downstream.
    usd_to_kzt: float | None = Field(default=None, gt=0, le=1_000_000)
    usd_to_rub: float | None = Field(default=None, gt=0, le=1_000_000)
    usd_to_uzs: float | None = Field(default=None, gt=0, le=1_000_000)


async def _load_org(db: AsyncSession, org_id: uuid.UUID) -> Organization:
    org = (
        await db.execute(select(Organization).where(Organization.id == org_id))
    ).scalar_one_or_none()
    if org is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    return org


@router.get("/settings", response_model=OrgSettingsOut)
async def get_org_settings(
    db: AsyncSession = Depends(get_db),
    org: uuid.UUID = Depends(get_org_id),
    _: User = Depends(get_current_user),
):
    """This company's exchange rates. Readable by anyone who can read a report."""
    return OrgSettingsOut.model_validate(await _load_org(db, org))


@router.put("/settings", response_model=OrgSettingsOut)
async def update_org_settings(
    data: OrgSettingsIn,
    db: AsyncSession = Depends(get_db),
    org: uuid.UUID = Depends(get_org_id),
    _: User = Depends(require_role(UserRole.admin)),
):
    """Set the rates. Admin only — they change what every past report reads as."""
    record = await _load_org(db, org)
    record.usd_to_kzt = data.usd_to_kzt
    record.usd_to_rub = data.usd_to_rub
    record.usd_to_uzs = data.usd_to_uzs
    record.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(record)
    return OrgSettingsOut.model_validate(record)
