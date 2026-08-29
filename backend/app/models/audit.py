from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AuditEvent(Base):
    """A record of something the platform operator did to a customer.

    Everything a superadmin can do is invisible from inside the tenant it
    happens to: a company sees its account suspended, or a user it did not
    create, or nothing at all when its data is merely read. Without this table
    there is no answer to "who did that, and when" — not for the customer
    asking, and not for us.

    Append-only by intent. Nothing in the application updates or deletes a row
    here; the value of the record is that it cannot be tidied afterwards by the
    person it describes.

    Actor email and organization name are copied in rather than joined. A log
    that says "user 3f2a… suspended org 91bc…" is useless once either row has
    been deleted, which — for a deletion event — is always.
    """

    __tablename__ = "audit_events"
    __table_args__ = (
        # The two questions actually asked of this table: "what happened
        # recently" and "what was ever done to this customer".
        Index("ix_audit_events_created_at", "created_at"),
        Index("ix_audit_events_target_org", "target_org_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # SET NULL, not CASCADE: removing a staff account must not erase the record
    # of what that account did.
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    actor_email: Mapped[str] = mapped_column(String(255), nullable=False)

    # A short verb, e.g. "organization.suspend" or "support.read".
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    # The customer this was done to. Deliberately not a foreign key: the row
    # must outlive the organization, and an organization deletion is precisely
    # the event most worth keeping.
    target_org_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    target_org_name: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Free-form context: the request path for a support read, the field that
    # changed for an update. Human-readable, because the reader is a human
    # answering a customer.
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
