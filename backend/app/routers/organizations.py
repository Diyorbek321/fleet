"""Platform-operator console: manage the customer companies on the platform.

Every endpoint here is superadmin-only. This is the *only* place where a request
crosses tenant boundaries — the fleet routers (``/api/trucks``, ``/api/trips``, …)
stay strictly scoped to ``get_org_id`` even for a superadmin, which is what keeps
the blast radius of the role small and every tenant-isolation test still honest.

Concretely, the operator does four things here: onboard a company (org + its first
admin, atomically), see how big each account is, suspend an account that stops
paying, and — rarely — delete one.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import hash_password
from app.deps.auth import require_role
from app.models.drivers import Driver
from app.models.enums import UserRole
from app.models.organizations import Organization
from app.models.trips import Trip
from app.models.trucks import Truck
from app.models.users import User
from app.schemas.auth import UserOut
from app.schemas.organizations import OrganizationCreate, OrganizationOut, OrganizationUpdate, OrgUserCreate

router = APIRouter(prefix="/api/organizations", tags=["Organizations"])

# One dependency instance reused by every route: a company admin hitting any of
# these gets 403, never a partial or filtered result.
_SUPERADMIN = require_role(UserRole.superadmin)

# Roles a superadmin may hand out through this router. ``superadmin`` is excluded
# so the platform role can never be minted over the API, and ``driver`` because a
# driver login must be created via /api/drivers/{id}/create-login to be linked to
# a Driver profile — an unlinked driver user can't use the mobile app at all.
_ASSIGNABLE_ROLES = (UserRole.admin, UserRole.manager, UserRole.operator)


def _count_of(model):
    """Correlated ``COUNT(*)`` of a tenant table for the Organization row in scope.

    Used as a scalar subquery so the list endpoint returns every org *and* its four
    counts in one statement instead of five queries per row.
    """
    return (
        select(func.count())
        .select_from(model)
        .where(model.org_id == Organization.id)
        .correlate(Organization)
        .scalar_subquery()
    )


def _select_orgs_with_counts():
    """SELECT of Organization plus its user/truck/driver/trip counts."""
    return select(
        Organization,
        _count_of(User).label("user_count"),
        _count_of(Truck).label("truck_count"),
        _count_of(Driver).label("driver_count"),
        _count_of(Trip).label("trip_count"),
    )


def _to_out(row) -> OrganizationOut:
    """Map a (Organization, user_count, truck_count, driver_count, trip_count) row."""
    org, user_count, truck_count, driver_count, trip_count = row
    return OrganizationOut(
        id=org.id,
        name=org.name,
        is_active=org.is_active,
        contact_name=org.contact_name,
        contact_phone=org.contact_phone,
        notes=org.notes,
        created_at=org.created_at,
        user_count=user_count,
        truck_count=truck_count,
        driver_count=driver_count,
        trip_count=trip_count,
    )


async def _get_org_row(db: AsyncSession, org_id: uuid.UUID):
    """Load one organization with its counts, or 404."""
    row = (await db.execute(_select_orgs_with_counts().where(Organization.id == org_id))).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    return row


@router.get("", response_model=list[OrganizationOut])
async def list_organizations(
    q: Optional[str] = Query(default=None, description="Case-insensitive name search"),
    db: AsyncSession = Depends(get_db),
    _superadmin: User = Depends(_SUPERADMIN),
):
    """All customer companies, newest first, with their fleet sizes."""
    stmt = _select_orgs_with_counts()
    if q:
        stmt = stmt.where(Organization.name.ilike(f"%{q.strip()}%"))
    res = await db.execute(stmt.order_by(Organization.created_at.desc()))
    return [_to_out(row) for row in res.all()]


@router.post("", response_model=OrganizationOut, status_code=201)
async def create_organization(
    data: OrganizationCreate = Body(...),
    db: AsyncSession = Depends(get_db),
    _superadmin: User = Depends(_SUPERADMIN),
):
    """Onboard a company: create the Organization and its first admin atomically.

    Both inserts share one transaction and only ``flush`` in between (to get the
    generated ``org.id``), so a failing user insert — a racing duplicate email, a
    constraint violation — rolls the organization back too. Half-provisioned
    tenants would otherwise pile up invisibly and still be billable.
    """
    existing = await db.execute(select(User).where(User.email == data.admin_email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")

    org = Organization(
        name=data.name,
        contact_name=data.contact_name,
        contact_phone=data.contact_phone,
        notes=data.notes,
    )
    db.add(org)
    await db.flush()  # assigns org.id without ending the transaction

    admin = User(
        org_id=org.id,
        email=data.admin_email,
        password_hash=hash_password(data.admin_password),
        role=UserRole.admin,
    )
    db.add(admin)
    await db.commit()
    await db.refresh(org)

    # A freshly created org has exactly one user and no fleet yet — no need to
    # re-run the counting query for numbers we already know.
    return OrganizationOut(
        id=org.id,
        name=org.name,
        is_active=org.is_active,
        contact_name=org.contact_name,
        contact_phone=org.contact_phone,
        notes=org.notes,
        created_at=org.created_at,
        user_count=1,
    )


@router.get("/{org_id}", response_model=OrganizationOut)
async def get_organization(
    org_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _superadmin: User = Depends(_SUPERADMIN),
):
    return _to_out(await _get_org_row(db, org_id))


@router.patch("/{org_id}", response_model=OrganizationOut)
async def update_organization(
    org_id: uuid.UUID,
    data: OrganizationUpdate = Body(...),
    db: AsyncSession = Depends(get_db),
    _superadmin: User = Depends(_SUPERADMIN),
):
    """Edit a company's details or flip its ``is_active`` suspension switch.

    Suspension is the billing lever: it takes effect on the customer's very next
    request (``get_current_user`` re-reads it) and is fully reversible, so an
    unpaid invoice never requires touching their data.
    """
    row = await _get_org_row(db, org_id)
    org: Organization = row[0]

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(org, field, value)
    org.updated_at = datetime.now(timezone.utc)

    await db.commit()
    return _to_out(await _get_org_row(db, org_id))


@router.delete("/{org_id}", status_code=204)
async def delete_organization(
    org_id: uuid.UUID,
    confirm: str | None = Query(None, description="Must equal the organization's exact name"),
    db: AsyncSession = Depends(get_db),
    superadmin: User = Depends(_SUPERADMIN),
):
    """Permanently delete a company and everything it owns.

    Cascade: every tenant table (``users``, ``trucks``, ``drivers``, ``trips``,
    ``devices``, ``geofences``, ``notifications``, ``trip_expense_reports``) declares
    ``ForeignKey("organizations.id", ondelete="CASCADE")``, and their children in
    turn cascade off ``trucks``/``trips``/``drivers``/``users`` (or SET NULL where the
    row outlives its parent, e.g. ``devices.truck_id``). So a single DELETE on
    ``organizations`` is enough — Postgres removes the rest. Verified against the
    FK definitions in ``app/models/``; note this relies on database-level cascades,
    which means the connection must be a real Postgres one (SQLite needs
    ``PRAGMA foreign_keys=ON`` to behave the same).

    Because it is unrecoverable, the caller must echo the exact organization name
    in ``?confirm=``. That parameter is declared optional so an omitted confirmation
    and a wrong one fall through the same guard and both answer 400 — a required
    Query would make the omitted case a 422 validation error, which reads to a
    client as "malformed request" rather than "refused, you must confirm".
    Deleting your own organization is refused outright: it would delete the caller
    mid-request and, for the Platform org, every superadmin login with it.
    """
    org = (
        await db.execute(select(Organization).where(Organization.id == org_id))
    ).scalar_one_or_none()
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")

    if org.id == superadmin.org_id:
        raise HTTPException(status_code=400, detail="Cannot delete your own organization")

    if confirm != org.name:
        raise HTTPException(status_code=400, detail="Confirmation does not match the organization name")

    await db.delete(org)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{org_id}/users", response_model=list[UserOut])
async def list_organization_users(
    org_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _superadmin: User = Depends(_SUPERADMIN),
):
    """Staff accounts of one company — who to contact, and who can still log in."""
    await _get_org_row(db, org_id)
    res = await db.execute(
        select(User).where(User.org_id == org_id).order_by(User.created_at.desc())
    )
    return res.scalars().all()


@router.post("/{org_id}/users", response_model=UserOut, status_code=201)
async def create_organization_user(
    org_id: uuid.UUID,
    data: OrgUserCreate = Body(...),
    db: AsyncSession = Depends(get_db),
    _superadmin: User = Depends(_SUPERADMIN),
):
    """Add a staff user to a company — the recovery path when its last admin is
    locked out, which support otherwise cannot fix without touching the database.
    """
    if data.role not in _ASSIGNABLE_ROLES:
        raise HTTPException(status_code=400, detail="Role must be admin, manager or operator")

    await _get_org_row(db, org_id)

    existing = await db.execute(select(User).where(User.email == data.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")

    user = User(
        org_id=org_id,
        email=data.email,
        password_hash=hash_password(data.password),
        role=data.role,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user
