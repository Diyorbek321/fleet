from __future__ import annotations

import uuid
from datetime import datetime, timezone
from sqlalchemy import Boolean, String, DateTime, Enum, ForeignKey, false
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base
from app.models.enums import UserRole

class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole, name="user_role"), default=UserRole.operator, nullable=False)
    # Links a "driver" role user to their Driver record so the mobile app can be self-scoped.
    driver_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("drivers.id", ondelete="SET NULL"), unique=True, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    # Stamped into every token this user is issued. A token minted before the
    # current value is rejected, which is what makes a password reset actually
    # end the sessions that were open when it happened — the refresh store is
    # keyed by token string and cannot be queried per user.
    password_changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    # Set when someone else sets this account's password, cleared when the user
    # picks their own. An admin-set password is one the admin knows.
    must_change_password: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), nullable=False
    )

    driver: Mapped["Driver"] = relationship("Driver", lazy="joined")
