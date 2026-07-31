"""Schemas for the platform-operator console (``/api/organizations``).

These are the only schemas in the codebase that describe *another* tenant's data,
so they are deliberately kept apart from the customer-facing ones: nothing here is
ever returned to a company's own admin. ``notes`` in particular is an internal
field (billing quirks, onboarding state) that must not leak outside superadmin
endpoints.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.models.enums import UserRole


class OrganizationCreate(BaseModel):
    """Provision a customer company and its first admin in one call.

    The admin credentials are part of *this* payload rather than a follow-up call
    because a company without an admin is unusable: creating them separately would
    leave a half-provisioned tenant behind whenever the second call never happens.
    The role of that first user is never taken from the request — it is always
    ``admin``.
    """
    name: str = Field(min_length=1, max_length=200)
    admin_email: EmailStr
    admin_password: str = Field(min_length=8, max_length=128)
    contact_name: str | None = Field(default=None, max_length=200)
    contact_phone: str | None = Field(default=None, max_length=40)
    notes: str | None = None


class OrganizationUpdate(BaseModel):
    """Partial update. Every field optional; only what is sent is applied.

    ``is_active=False`` is the suspension switch — see the Organization model for
    what that does to the customer's logins.
    """
    name: str | None = Field(default=None, min_length=1, max_length=200)
    is_active: bool | None = None
    contact_name: str | None = Field(default=None, max_length=200)
    contact_phone: str | None = Field(default=None, max_length=40)
    notes: str | None = None


class OrganizationOut(BaseModel):
    """A customer company plus the size of its fleet.

    The four counts are what the operator actually looks at (is this account
    growing? is it worth keeping?), so they are part of the row rather than a
    separate endpoint — the list query computes them with correlated subqueries in
    a single statement.
    """
    id: uuid.UUID
    name: str
    is_active: bool
    contact_name: str | None = None
    contact_phone: str | None = None
    notes: str | None = None
    created_at: datetime
    user_count: int = 0
    truck_count: int = 0
    driver_count: int = 0
    trip_count: int = 0

    class Config:
        from_attributes = True


class OrgUserCreate(BaseModel):
    """Add a staff user to any organization (superadmin only).

    ``role`` is validated in the router against admin|manager|operator rather than
    accepting the full ``UserRole``: ``superadmin`` would be privilege escalation
    into the platform itself, and ``driver`` must go through ``/api/drivers`` so
    the user is linked to a Driver profile the mobile app can scope to.
    """
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    role: UserRole = UserRole.operator
