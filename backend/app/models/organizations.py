from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Organization(Base):
    """A tenant. Every fleet customer is one organization; all tenant-owned data
    (trucks, drivers, devices, geofences, trips, …) carries an ``org_id`` FK and
    every query is scoped to the signed-in user's organization.

    The first user to sign up via ``POST /api/auth/register`` creates a new
    organization and becomes its admin. Additional users are provisioned by that
    admin and inherit the same ``org_id``.
    """

    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
