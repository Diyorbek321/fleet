from __future__ import annotations
from pydantic import BaseModel, EmailStr, Field
from typing import Optional
import uuid
from app.models.enums import UserRole

class RegisterIn(BaseModel):
    """Self-service sign-up. Creates a brand-new organization and its first admin.

    Only accepted when ``settings.allow_public_registration`` is on (it is off by
    default — companies are provisioned by the platform operator through
    ``POST /api/organizations``).

    The role is intentionally NOT accepted from the client — the first user of a
    new org is always the admin. Additional users are provisioned by that admin
    via ``POST /api/auth/users``.
    """
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    org_name: str = Field(min_length=1, max_length=200)

class CreateUserIn(BaseModel):
    """Admin-only: add an admin, manager or operator to the admin's own organization."""
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    role: UserRole = UserRole.operator


class UpdateUserIn(BaseModel):
    """Admin-only: change a colleague's role and/or reset their password.

    Both fields optional — a password reset and a promotion are separate everyday
    actions and neither should force the caller to restate the other. The router
    enforces who may be targeted (same org, not a driver, never ``superadmin``,
    never yourself).
    """
    role: Optional[UserRole] = None
    password: Optional[str] = Field(default=None, min_length=8, max_length=128)

class LoginIn(BaseModel):
    email: EmailStr
    password: str

class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"

class UserOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    email: str
    role: UserRole

    class Config:
        from_attributes = True


class RefreshIn(BaseModel):
    refresh_token: str


class LogoutIn(BaseModel):
    refresh_token: str
