from __future__ import annotations
from pydantic import BaseModel, EmailStr, Field
from typing import Optional
import uuid
from app.models.enums import UserRole

class RegisterIn(BaseModel):
    """Public sign-up. Creates a brand-new organization and its first admin user.

    The role is intentionally NOT accepted from the client — the first user of a
    new org is always the admin. Additional users are provisioned by that admin
    via ``POST /api/auth/users``.
    """
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    org_name: str = Field(min_length=1, max_length=200)

class CreateUserIn(BaseModel):
    """Admin-only: add a manager or operator to the admin's own organization."""
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    role: UserRole = UserRole.operator

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
