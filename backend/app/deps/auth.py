from __future__ import annotations

import uuid

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.core.security import decode_token, token_predates_password_change
from app.models.organizations import Organization
from app.models.users import User
from app.models.enums import UserRole

bearer = HTTPBearer(auto_error=False)

async def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Resolve the caller from the bearer token and reject suspended tenants.

    The organization is loaded with an inner join in the *same* query that already
    fetches the user, not as a second round-trip: this runs on every authenticated
    request, so an extra SELECT here would be an extra SELECT platform-wide.

    A suspended organization (``is_active = False`` — unpaid invoice, offboarded
    customer) gets 403 rather than 401 so the client can tell "your company is
    switched off" apart from "your session expired" and stop retrying the login.
    Superadmins are exempt: suspending the "Platform" org must not lock the
    operator out of the very endpoint needed to un-suspend a customer.
    """
    if creds is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    token = creds.credentials
    try:
        payload = decode_token(token)
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    user_id_raw = payload.get("userId")
    if not user_id_raw:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload")

    try:
        user_id = uuid.UUID(user_id_raw)
    except (ValueError, TypeError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload")

    res = await db.execute(
        select(User, Organization.is_active)
        .join(Organization, Organization.id == User.org_id)
        .where(User.id == user_id)
    )
    row = res.first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    user, org_is_active = row

    # A password change ends every session it did not create. The refresh store
    # is keyed by token string and cannot be asked for "all of this user's
    # tokens", so the check lives here: any token stamped before the account's
    # current password is refused, on every device at once.
    if token_predates_password_change(payload, user.password_changed_at):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Password changed — please sign in again",
        )

    if not org_is_active and user.role is not UserRole.superadmin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organization is suspended")
    return user

def require_role(*roles: UserRole):
    async def _dep(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return user
    return _dep


async def get_org_id(user: User = Depends(get_current_user)) -> uuid.UUID:
    """The signed-in user's organization id.

    Every tenant-scoped query filters on this. Read from the DB-loaded user
    record (the source of truth), never trusted from a request body, so a user
    can only ever touch their own organization's data.
    """
    return user.org_id


async def get_current_driver(user: User = Depends(get_current_user)) -> "Driver":
    """Resolve the Driver record for the authenticated user.

    Used by all ``/api/me`` endpoints so the mobile app is strictly scoped to
    the signed-in driver's own data. Requires the user to be linked to a Driver.
    """
    if user.driver_id is None or user.driver is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account is not linked to a driver profile",
        )
    return user.driver
