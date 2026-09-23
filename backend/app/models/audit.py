from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AuditEvent(Base):
    """A record of something consequential that someone did, and to what.

    Two audiences, one table. The platform operator's actions on a customer are
    invisible from inside the tenant they happen to: a company sees its account
    suspended, or a user it did not create, or nothing at all when its data is
    merely read. And inside a tenant, the figures an owner runs the business on
    are editable by their own staff — a trip can be deleted, its rate rewritten,
    the USD rate that converts every cross-border expense report moved by one
    number. Both need an answer to "who did that, and when".

    (Fuel logs are not in that list on purpose: there is no route that edits or
    deletes one, so the litres a leakage report reads cannot be revised after
    the fact. Deleting the *trip* they hang off is the way that number moves,
    which is why trip deletion is audited here.)

    Append-only by intent. Nothing in the application updates or deletes a row
    here; the value of the record is that it cannot be tidied afterwards by the
    person it describes.

    Actor email and organization name are copied in rather than joined. A log
    that says "user 3f2a… suspended org 91bc…" is useless once either row has
    been deleted, which — for a deletion event — is always. ``target_label``
    exists for the same reason at the record level: "trip UZ-000412 to Almaty,
    rate 42 000 000" still reads after the trip is gone.
    """

    __tablename__ = "audit_events"
    __table_args__ = (
        # The two questions actually asked of this table: "what happened
        # recently" and "what was ever done to this customer".
        Index("ix_audit_events_created_at", "created_at"),
        Index("ix_audit_events_target_org", "target_org_id", "created_at"),
        # "What has been done to this record" — the question an owner asks
        # after noticing a trip is missing.
        Index("ix_audit_events_target", "target_type", "target_id"),
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

    # What the action was done to, when it was a record inside a tenant rather
    # than the tenant itself: "trip", "truck", "org_settings". Null for the
    # platform-level actions, whose target is the organization.
    target_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Not a foreign key, and for the same reason target_org_id is not: the row
    # must outlive the record, and a deletion is the event most worth keeping.
    target_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    # How a human recognises that record — a plate, a trip reference, a name.
    target_label: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Free-form context: the request path for a support read, the field that
    # changed for an update. Human-readable, because the reader is a human
    # answering a customer.
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
