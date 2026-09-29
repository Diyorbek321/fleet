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
from app.services import audit
from app.services.trip_orders import DEFAULT_RULES
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Компания не найдена")
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
    actor: User = Depends(require_role(UserRole.admin)),
):
    """Set the rates. Admin only — they change what every past report reads as."""
    record = await _load_org(db, org)
    fields = ("usd_to_kzt", "usd_to_rub", "usd_to_uzs")
    before = {f: getattr(record, f) for f in fields}

    record.usd_to_kzt = data.usd_to_kzt
    record.usd_to_rub = data.usd_to_rub
    record.usd_to_uzs = data.usd_to_uzs
    record.updated_at = datetime.now(timezone.utc)

    # These retroactively restate every cross-border expense report the company
    # has ever filed. One number moved by an operator can change a quarter's
    # figures, and nothing else in the product would show that it happened.
    changed = audit.describe_changes(
        before, {f: getattr(record, f) for f in fields}, fields
    )
    if changed:
        await audit.record_change(
            db,
            actor=actor,
            action=audit.SETTINGS_UPDATE,
            org_id=org,
            target_type="org_settings",
            target_id=org,
            target_label="exchange rates",
            detail=changed,
        )

    await db.commit()
    await db.refresh(record)
    return OrgSettingsOut.model_validate(record)


# ── Order sheet template ─────────────────────────────────────────────────
#
# The two parts of a truck group's order post that belong to the company
# rather than the trip. See app/services/trip_orders.py for the layout.


class TripOrderTemplateOut(BaseModel):
    # None = the built-in list is in use; ``default_rules`` shows what that is,
    # so the form can start from it instead of from an empty box.
    rules: str | None = None
    footer: str | None = None
    default_rules: str


class TripOrderTemplateIn(BaseModel):
    rules: str | None = Field(default=None, max_length=2000)
    footer: str | None = Field(default=None, max_length=500)


def _blank_to_none(value: str | None) -> str | None:
    return value.strip() if value and value.strip() else None


@router.get("/trip-order-template", response_model=TripOrderTemplateOut)
async def get_trip_order_template(
    db: AsyncSession = Depends(get_db),
    org: uuid.UUID = Depends(get_org_id),
    _: User = Depends(require_role(UserRole.admin, UserRole.manager, UserRole.operator)),
):
    record = await _load_org(db, org)
    return TripOrderTemplateOut(
        rules=record.trip_order_rules, footer=record.trip_order_footer, default_rules=DEFAULT_RULES
    )


@router.put("/trip-order-template", response_model=TripOrderTemplateOut)
async def update_trip_order_template(
    data: TripOrderTemplateIn,
    db: AsyncSession = Depends(get_db),
    org: uuid.UUID = Depends(get_org_id),
    _: User = Depends(require_role(UserRole.admin, UserRole.manager)),
):
    """Empty rules go back to the built-in list; an empty footer drops the line."""
    record = await _load_org(db, org)
    rules = _blank_to_none(data.rules)
    record.trip_order_rules = None if rules == DEFAULT_RULES else rules
    record.trip_order_footer = _blank_to_none(data.footer)
    record.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return TripOrderTemplateOut(
        rules=record.trip_order_rules, footer=record.trip_order_footer, default_rules=DEFAULT_RULES
    )
