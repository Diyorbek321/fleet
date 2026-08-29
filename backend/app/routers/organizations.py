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
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Response, status
from sqlalchemy import desc, func, select
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import hash_password
from app.services import audit
from app.deps.auth import require_role
from app.models.audit import AuditEvent
from app.models.drivers import Driver
from app.models.enums import UserRole
from app.models.organizations import Organization
from app.models.trips import Trip
from app.models.trucks import Truck, TruckLocationHistory
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
    await audit.record(
        db,
        actor=_superadmin,
        action=audit.ORG_CREATE,
        org=org,
        detail=f"first admin {data.admin_email}",
    )
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

    changes = data.model_dump(exclude_unset=True)
    was_active = org.is_active
    for field, value in changes.items():
        setattr(org, field, value)
    org.updated_at = datetime.now(timezone.utc)

    # Suspension is logged as its own action, not as a field edit. It is the
    # one change a customer feels immediately, and it is the first thing they
    # ask about — burying it in "fields changed: is_active" would mean reading
    # every update event to find it.
    if "is_active" in changes and changes["is_active"] != was_active:
        action = audit.ORG_REACTIVATE if changes["is_active"] else audit.ORG_SUSPEND
        await audit.record(db, actor=_superadmin, action=action, org=org)
    other = sorted(k for k in changes if k != "is_active")
    if other:
        await audit.record(
            db,
            actor=_superadmin,
            action=audit.ORG_UPDATE,
            org=org,
            detail="changed: " + ", ".join(other),
        )

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

    # Recorded before the delete, and with the name copied in: after the
    # commit there is nothing left to describe what was removed. This is the
    # event most worth keeping and the only one whose subject no longer exists.
    await audit.record(
        db,
        actor=superadmin,
        action=audit.ORG_DELETE,
        org_id=org.id,
        org_name=org.name,
        detail="permanent, cascaded to all tenant data",
    )
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
    await audit.record(
        db,
        actor=_superadmin,
        action=audit.ORG_USER_CREATE,
        org_id=org_id,
        detail=f"{data.email} as {data.role.value}",
    )
    await db.commit()
    await db.refresh(user)
    return user


# ── Platform overview ────────────────────────────────────────────────────────


class PlatformStats(BaseModel):
    """The whole book of business in one row.

    The per-organization counts on the list above answer "how is this customer
    doing"; nobody can answer "how are we doing" by adding up a paginated
    table in their head.
    """

    organizations: int
    active_organizations: int
    suspended_organizations: int
    users: int
    drivers: int
    trucks: int
    trips: int
    trips_last_30d: int
    gps_points: int


@router.get("/platform/stats", response_model=PlatformStats)
async def platform_stats(
    db: AsyncSession = Depends(get_db),
    _superadmin: User = Depends(_SUPERADMIN),
):
    """Totals across every customer. Superadmin-only, and counts only.

    Deliberately aggregate: this crosses the tenant boundary that the rest of
    the API exists to hold, so it returns numbers no one customer's data can be
    reconstructed from. Looking at an individual company's fleet goes through
    the audited support path instead.

    The Platform organization itself is excluded from the organization counts —
    it holds no fleet and counting ourselves as a customer would overstate the
    business by one on every screen it appears.
    """
    since = datetime.now(timezone.utc) - timedelta(days=30)

    async def count(stmt) -> int:
        return (await db.execute(stmt)).scalar() or 0

    orgs_total = await count(
        select(func.count(Organization.id)).where(Organization.id != _superadmin.org_id)
    )
    orgs_active = await count(
        select(func.count(Organization.id)).where(
            Organization.id != _superadmin.org_id, Organization.is_active.is_(True)
        )
    )

    return PlatformStats(
        organizations=orgs_total,
        active_organizations=orgs_active,
        suspended_organizations=orgs_total - orgs_active,
        users=await count(select(func.count(User.id))),
        drivers=await count(select(func.count(Driver.id))),
        trucks=await count(select(func.count(Truck.id))),
        trips=await count(select(func.count(Trip.id))),
        trips_last_30d=await count(
            select(func.count(Trip.id)).where(Trip.created_at >= since)
        ),
        gps_points=await count(select(func.count(TruckLocationHistory.id))),
    )


# ── Audit trail ──────────────────────────────────────────────────────────────


class AuditEventOut(BaseModel):
    id: uuid.UUID
    actor_email: str
    action: str
    target_org_id: Optional[uuid.UUID]
    target_org_name: Optional[str]
    detail: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


@router.get("/platform/audit", response_model=list[AuditEventOut])
async def audit_log(
    db: AsyncSession = Depends(get_db),
    _superadmin: User = Depends(_SUPERADMIN),
    org_id: Optional[uuid.UUID] = Query(None, description="Only events about this customer"),
    limit: int = Query(default=100, ge=1, le=500),
):
    """What the platform operator has done, newest first.

    Read-only by design: there is no endpoint to edit or delete an event, and
    the application never writes one. A log the subject can tidy afterwards
    answers nothing.
    """
    stmt = select(AuditEvent).order_by(desc(AuditEvent.created_at)).limit(limit)
    if org_id is not None:
        stmt = stmt.where(AuditEvent.target_org_id == org_id)
    return (await db.execute(stmt)).scalars().all()
