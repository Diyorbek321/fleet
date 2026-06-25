import uuid

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.core.rate_limit import limiter
from app.core.security import hash_password, verify_password, create_access_token, create_refresh_token, decode_token
from app.schemas.auth import RegisterIn, CreateUserIn, LoginIn, TokenOut, UserOut, RefreshIn, LogoutIn
from app.models.organizations import Organization
from app.models.users import User
from app.models.enums import UserRole
from app.services.refresh_tokens import refresh_store
from app.deps.auth import get_current_user, require_role

router = APIRouter(prefix="/api/auth", tags=["Auth"])


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
    """Public sign-up: provisions a new organization and its first admin user.

    Role is never taken from the request — the first user of a fresh org is
    always the admin, closing the privilege-escalation hole where a caller could
    self-assign ``admin``.
    """
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
    """Admin-only: add a manager or operator to the admin's own organization."""
    if data.role not in (UserRole.manager, UserRole.operator):
        raise HTTPException(status_code=400, detail="Role must be manager or operator")

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

@router.post("/login", response_model=TokenOut)
@limiter.limit("10/minute")
async def login(request: Request, data: LoginIn = Body(...), db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(User).where(User.email == data.email))
    user = res.scalar_one_or_none()
    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    subject = _token_subject(user)
    access = create_access_token(subject)
    refresh = create_refresh_token(subject)
    await refresh_store.put(refresh)
    return TokenOut(access_token=access, refresh_token=refresh)

@router.post("/refresh", response_model=TokenOut)
async def refresh_token(data: RefreshIn, db: AsyncSession = Depends(get_db)):
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
    res = await db.execute(select(User).where(User.id == user_id))
    user = res.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

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
