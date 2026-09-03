from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Numeric, String, DateTime, Text, func, true
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Organization(Base):
    """A tenant. Every fleet customer is one organization; all tenant-owned data
    (trucks, drivers, devices, geofences, trips, …) carries an ``org_id`` FK and
    every query is scoped to the signed-in user's organization.

    Organizations are normally provisioned by the platform operator through
    ``POST /api/organizations`` (which creates the org and its first admin user
    in one transaction). Public self-service sign-up via
    ``POST /api/auth/register`` is off by default — see
    ``settings.allow_public_registration``. Additional users are provisioned by
    the company's own admin and inherit the same ``org_id``.

    ``is_active`` is the suspension switch: flipping it to ``False`` (an unpaid
    invoice, an offboarded customer) makes every login and every authenticated
    request from that org fail with 403 while leaving the data untouched, so
    the customer can be reinstated by flipping it back. Superadmins are exempt
    — otherwise suspending the platform org would lock the operator out of the
    very endpoint needed to un-suspend it.

    The superadmin's own organization (named "Platform") is a degenerate tenant:
    it exists only because ``users.org_id`` is NOT NULL and it holds no trucks,
    drivers or trips. Do not expect fleet data in it, and do not treat it as a
    customer when reporting on organizations.
    """

    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # False = suspended. Checked on every authenticated request, so it is a plain
    # column rather than a status enum: the auth hot path only ever asks yes/no.
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )
    # Who to call at the customer. Deliberately free-form single fields instead of
    # a contacts table: the platform operator deals with one person per company.
    contact_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # Internal notes for the platform operator (billing quirks, onboarding state).
    # Never exposed to the customer's own admins — only /api/organizations/* reads it.
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # How many units of each currency one US dollar buys, for comparing a trip's
    # Kazakh, Russian and Uzbek spending on one scale. NULL means "not set": the
    # report then shows native amounts only and says so, rather than converting
    # at a rate nobody chose. A trip that recorded its own exchange (dollars
    # handed over, tenge received) overrides these — see
    # ``app.services.country_expenses.resolve_rates``.
    usd_to_kzt: Mapped[float | None] = mapped_column(Numeric(14, 4), nullable=True)
    usd_to_rub: Mapped[float | None] = mapped_column(Numeric(14, 4), nullable=True)
    usd_to_uzs: Mapped[float | None] = mapped_column(Numeric(14, 4), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        nullable=False,
    )
