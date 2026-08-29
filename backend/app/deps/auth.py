from __future__ import annotations

import uuid

from fastapi import Depends, HTTPException, Request, status
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
    """Gate an endpoint on the caller's role.

    A superadmin satisfies every requirement. Roles answer "is this the kind of
    work you do here"; the question of *whose* data you touch is answered
    separately by ``get_org_id``, and that is the boundary protecting customers.
    Without it a platform operator could pass every role check and still see
    nothing but their own empty Platform organization.

    This is what lets the audited support path reach the screens support calls
    are actually about — a customer reporting a wrong fuel figure is reporting
    it about analytics, which is gated on the tenant roles. Reaching those
    screens still requires the ``X-Support-Org`` header, still refuses anything
    but a safe method, and is still written to the audit log.
    """
    allowed = frozenset(roles) | {UserRole.superadmin}

    async def _dep(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return user
    return _dep


# Header a platform operator sets to look at one customer's data while helping
# them. Named for what it is: nothing else in the API reads it, and it appears
# in the audit log under exactly this name.
SUPPORT_ORG_HEADER = "X-Support-Org"

# Methods a support session may use. Reading a customer's screen is how you
# answer "my leakage page is wrong"; writing into their tenant is how you
# become the reason their numbers changed. The operator has POST
# /api/organizations/{id}/users for the one write they legitimately need.
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


async def get_org_id(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> uuid.UUID:
    """The organization whose data this request may touch.

    Normally the signed-in user's own, read from the DB-loaded record and never
    from anything in the request — which is what keeps one customer out of
    another's data across all sixty-odd call sites.

    A superadmin may override it with the ``X-Support-Org`` header to read one
    customer while helping them. That is a deliberate hole in the isolation
    boundary, so it is fenced on every side: superadmin only, safe methods
    only, the organization must exist, and every session is written to the
    audit log. A customer who asks "who looked at my data" gets an answer.
    """
    requested = request.headers.get(SUPPORT_ORG_HEADER)
    if not requested:
        return user.org_id

    if user.role is not UserRole.superadmin:
        # 403, not "ignore the header": a tenant user sending this is either
        # probing the boundary or running a client that believes it can cross
        # it. Silently serving their own data would hide both.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Support access is restricted to platform operators",
        )

    if request.method.upper() not in _SAFE_METHODS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Support access is read-only",
        )

    try:
        target_id = uuid.UUID(requested)
    except (ValueError, TypeError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid organization id")

    org = (
        await db.execute(select(Organization).where(Organization.id == target_id))
    ).scalar_one_or_none()
    if org is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")

    from app.services.audit import record_support_read

    await record_support_read(db, actor=user, org=org, path=request.url.path)
    return org.id


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
