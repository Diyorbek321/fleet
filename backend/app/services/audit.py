"""Recording what the platform operator did to a customer.

Kept apart from the routers so there is one definition of an audit event and
one place that decides what is worth a row.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger
from app.models.audit import AuditEvent
from app.models.organizations import Organization
from app.models.users import User

# Actions. Strings rather than an enum: the set grows with the product, and a
# migration to add a value to a Postgres enum is a poor trade for a log column.
ORG_CREATE = "organization.create"
ORG_UPDATE = "organization.update"
ORG_SUSPEND = "organization.suspend"
ORG_REACTIVATE = "organization.reactivate"
ORG_DELETE = "organization.delete"
ORG_USER_CREATE = "organization.user.create"
SUPPORT_READ = "support.read"

# A superadmin opening one customer screen fires half a dozen requests, and a
# support session would otherwise bury the deliberate actions under hundreds of
# near-identical rows. One entry per operator per customer per window keeps the
# log answerable by a human, which is the only reason it exists.
SUPPORT_READ_WINDOW = timedelta(minutes=10)


async def record(
    db: AsyncSession,
    *,
    actor: User,
    action: str,
    org: Organization | None = None,
    org_id: uuid.UUID | None = None,
    org_name: str | None = None,
    detail: str | None = None,
) -> None:
    """Append one event. Never raises.

    A failure to log must not fail the action being logged: the customer's
    suspension either happened or it did not, and turning a logging problem
    into a 500 would leave the operator retrying an operation that already
    succeeded. The failure is shouted into the application log instead, where
    it reaches Sentry.
    """
    try:
        db.add(
            AuditEvent(
                actor_user_id=actor.id,
                # Copied, not joined: "user 3f2a… deleted org 91bc…" is useless
                # once either row is gone — which, for a deletion, is always.
                actor_email=actor.email,
                action=action,
                target_org_id=org.id if org else org_id,
                target_org_name=org.name if org else org_name,
                detail=detail,
            )
        )
        await db.flush()
    except Exception:  # noqa: BLE001 — see docstring
        logger.exception("audit_write_failed", action=action)


async def record_support_read(
    db: AsyncSession, *, actor: User, org: Organization, path: str
) -> None:
    """Note that the operator looked at a customer's data, at most once a window.

    Committed on its own rather than left to the request's session. The
    requests this fires on are reads, and a read handler has no commit of its
    own — without one the row would be discarded at the end of the request and
    the access would go unrecorded, which is the exact failure this is for.
    """
    try:
        since = datetime.now(timezone.utc) - SUPPORT_READ_WINDOW
        recent = (
            await db.execute(
                select(AuditEvent.id).where(
                    AuditEvent.actor_user_id == actor.id,
                    AuditEvent.target_org_id == org.id,
                    AuditEvent.action == SUPPORT_READ,
                    AuditEvent.created_at >= since,
                )
            )
        ).first()
        if recent:
            return

        db.add(
            AuditEvent(
                actor_user_id=actor.id,
                actor_email=actor.email,
                action=SUPPORT_READ,
                target_org_id=org.id,
                target_org_name=org.name,
                detail=f"support session opened at {path}",
            )
        )
        await db.commit()
        logger.info(
            "support_access", actor=actor.email, org=org.name, org_id=str(org.id), path=path
        )
    except Exception:  # noqa: BLE001
        logger.exception("audit_support_read_failed", org_id=str(org.id))
