import uuid

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.config import settings
from app.core.database import get_db
from app.core.rate_limit import limiter
from app.core.security import hash_password, verify_password, create_access_token, create_refresh_token, decode_token
from app.schemas.auth import RegisterIn, CreateUserIn, UpdateUserIn, LoginIn, TokenOut, UserOut, RefreshIn, LogoutIn
from app.models.organizations import Organization
from app.models.users import User
from app.models.enums import UserRole
from app.services.refresh_tokens import refresh_store
from app.deps.auth import get_current_user, require_role

router = APIRouter(prefix="/api/auth", tags=["Auth"])

# Roles a company's own admin may hand out or set. Excludes ``superadmin`` (the
# platform role — granting it here would be escalation out of the tenant) and
# ``driver`` (created via /api/drivers so the login is linked to a Driver profile).
_ORG_ASSIGNABLE_ROLES = (UserRole.admin, UserRole.manager, UserRole.operator)


def _token_subject(user: User) -> dict:
    return {
        "userId": str(user.id),
        "orgId": str(user.org_id),
        "email": user.email,
        "role": user.role.value,
    }


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)):
    return user

@router.post("/register", response_model=UserOut, status_code=201)
@limiter.limit("5/minute")
async def register(request: Request, data: RegisterIn = Body(...), db: AsyncSession = Depends(get_db)):
    """Self-service sign-up: provisions a new organization and its first admin user.

    Disabled by default and gated on ``settings.allow_public_registration``.
    FleetWatch is sold company by company, so tenants are normally provisioned by
    the platform operator via ``POST /api/organizations``; leaving an open sign-up
    endpoint on a paid product would let anyone mint a tenant. Enable it only for
    demo or staging deployments.

    Role is never taken from the request — the first user of a fresh org is
    always the admin, closing the privilege-escalation hole where a caller could
    self-assign ``admin``.
    """
    if not settings.allow_public_registration:
        raise HTTPException(status_code=403, detail="Public registration is disabled")

    existing = await db.execute(select(User).where(User.email == data.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")

    org = Organization(name=data.org_name)
    db.add(org)
    await db.flush()  # assign org.id

    user = User(
        org_id=org.id,
        email=data.email,
        password_hash=hash_password(data.password),
        role=UserRole.admin,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@router.post("/users", response_model=UserOut, status_code=201)
async def create_user(
    data: CreateUserIn = Body(...),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_role(UserRole.admin)),
):
    """Admin-only: add an admin, manager or operator to the admin's own organization.

    ``admin`` is allowed so a company can have a second owner and does not depend
    on us to recover a locked-out account. ``superadmin`` never is — that is the
    platform role and granting it here would be escalation out of the tenant.
    ``driver`` never is either: driver logins are created through
    ``POST /api/drivers/{id}/create-login`` so they are linked to a Driver profile.
    """
    if data.role not in _ORG_ASSIGNABLE_ROLES:
        raise HTTPException(status_code=400, detail="Role must be admin, manager or operator")

    existing = await db.execute(select(User).where(User.email == data.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")

    user = User(
        org_id=admin.org_id,
        email=data.email,
        password_hash=hash_password(data.password),
        role=data.role,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user

async def _get_colleague(db: AsyncSession, user_id: uuid.UUID, admin: User) -> User:
    """Load a user from the *caller's own* organization, or 404.

    The org filter comes from ``admin.org_id`` — the DB-loaded caller — never from
    anything in the request. A user in another organization returns 404 rather than
    403, matching the convention the rest of the API (and ``tests/test_tenancy.py``)
    follows: a 403 would confirm that the id exists somewhere on the platform.

    Superadmins are invisible here even to an admin of the same organization. The
    operator's own "Platform" org can legitimately contain company admins (support
    staff added via ``POST /api/organizations/{id}/users``), and without this filter
    one of them could ``PATCH`` a new password onto the superadmin account and take
    over every customer on the platform.
    """
    user = (
        await db.execute(
            select(User).where(
                User.id == user_id,
                User.org_id == admin.org_id,
                User.role != UserRole.superadmin,
            )
        )
    ).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.get("/users", response_model=list[UserOut])
async def list_users(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_role(UserRole.admin)),
):
    """Admin-only: the staff accounts of the caller's own organization."""
    res = await db.execute(
        select(User).where(User.org_id == admin.org_id).order_by(User.created_at.desc())
    )
    return res.scalars().all()


@router.patch("/users/{user_id}", response_model=UserOut)
async def update_user(
    user_id: uuid.UUID,
    data: UpdateUserIn = Body(...),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_role(UserRole.admin)),
):
    """Admin-only: change a colleague's role or reset their password.

    Three refusals, all deliberate:
    * a ``driver``'s role is immutable here — their account is bound to a Driver
      profile, and re-roling them would leave the mobile app pointing at nothing;
    * ``superadmin`` can never be set, or a tenant admin could promote themselves
      onto the platform;
    * you cannot change your own role, which is how an organization ends up with
      zero admins and needs us to unlock it.
    """
    target = await _get_colleague(db, user_id, admin)
    payload = data.model_dump(exclude_unset=True)

    if "role" in payload and payload["role"] is not None:
        new_role: UserRole = payload["role"]
        if target.id == admin.id:
            raise HTTPException(status_code=400, detail="Cannot change your own role")
        if target.role is UserRole.driver:
            raise HTTPException(status_code=400, detail="Cannot change a driver's role")
        if new_role not in _ORG_ASSIGNABLE_ROLES:
            raise HTTPException(status_code=400, detail="Role must be admin, manager or operator")
        target.role = new_role

    if payload.get("password"):
        target.password_hash = hash_password(payload["password"])

    await db.commit()
    await db.refresh(target)
    return target


@router.delete("/users/{user_id}", status_code=204)
async def delete_user(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_role(UserRole.admin)),
):
    """Admin-only: remove a colleague from the caller's own organization.

    Deleting yourself is refused — it is never what an admin means to do, and it
    can strand an organization with no one able to administer it.
    """
    target = await _get_colleague(db, user_id, admin)
    if target.id == admin.id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")

    await db.delete(target)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/login", response_model=TokenOut)
@limiter.limit("10/minute")
async def login(request: Request, data: LoginIn = Body(...), db: AsyncSession = Depends(get_db)):
    """Exchange credentials for an access + refresh token pair.

    The organization is joined in so a suspended tenant is stopped at the door with
    the same 403 the rest of the API returns, instead of handing out a token that
    every subsequent request would reject. Superadmins are exempt — see
    ``get_current_user``.
    """
    res = await db.execute(
        select(User, Organization.is_active)
        .join(Organization, Organization.id == User.org_id)
        .where(User.email == data.email)
    )
    row = res.first()
    user = row[0] if row else None
    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if not row[1] and user.role is not UserRole.superadmin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organization is suspended")

    subject = _token_subject(user)
    access = create_access_token(subject)
    refresh = create_refresh_token(subject)
    await refresh_store.put(refresh)
    return TokenOut(access_token=access, refresh_token=refresh)

@router.post("/refresh", response_model=TokenOut)
async def refresh_token(data: RefreshIn, db: AsyncSession = Depends(get_db)):
    """Rotate a refresh token into a fresh access + refresh pair.

    The organization is re-checked here for the same reason ``login`` checks it:
    this endpoint mints tokens, and a refresh token lives for
    ``settings.refresh_token_expire_days``. Without the check a client that was
    already signed in when its company got suspended could keep rotating itself a
    valid access token indefinitely, which is also a fresh ticket into ``/ws``.
    """
    token = data.refresh_token
    # Confirm token exists in store first (allows revoke)
    if not await refresh_store.exists(token):
        raise HTTPException(status_code=401, detail="Refresh token revoked or expired")

    try:
        payload = decode_token(token)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    if payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Not a refresh token")

    # Optionally: ensure user still exists
    try:
        user_id = uuid.UUID(payload.get("userId", ""))
    except (ValueError, TypeError):
        raise HTTPException(status_code=401, detail="Invalid token payload")
    res = await db.execute(
        select(User, Organization.is_active)
        .join(Organization, Organization.id == User.org_id)
        .where(User.id == user_id)
    )
    row = res.first()
    if row is None:
        raise HTTPException(status_code=401, detail="User not found")
    user, org_is_active = row
    if not org_is_active and user.role is not UserRole.superadmin:
        raise HTTPException(status_code=403, detail="Organization is suspended")

    subject = _token_subject(user)
    access = create_access_token(subject)
    new_refresh = create_refresh_token(subject)

    # Rotate refresh token
    await refresh_store.revoke(token)
    await refresh_store.put(new_refresh)

    return TokenOut(access_token=access, refresh_token=new_refresh)

@router.post("/logout")
async def logout(data: LogoutIn):
    await refresh_store.revoke(data.refresh_token)
    return {"message": "Logged out"}
