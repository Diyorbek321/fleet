"""What changed inside one fleet, and who changed it.

The platform's own audit view (``/api/organizations/platform/audit``) answers
that question for the operator, about customers. This one answers it for the
customer, about their own staff — and without it the record would exist while
the only person who needs it could not read it.

Admin only. Managers and operators can delete a trip and edit a rate; the point
of the log is that the people who can do those things are not the people who
decide what it says.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.deps.auth import get_org_id, require_role
from app.models.audit import AuditEvent
from app.models.enums import UserRole

router = APIRouter(prefix="/api/audit", tags=["Audit"])


class AuditEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    actor_email: str
    action: str
    target_type: Optional[str] = None
    target_id: Optional[uuid.UUID] = None
    target_label: Optional[str] = None
    detail: Optional[str] = None
    created_at: datetime


@router.get("", response_model=list[AuditEntryOut])
async def list_audit_entries(
    db: AsyncSession = Depends(get_db),
    org: uuid.UUID = Depends(get_org_id),
    _admin=Depends(require_role(UserRole.admin)),
    action: Optional[str] = Query(default=None, description="Filter to one action"),
    target_type: Optional[str] = Query(default=None),
    target_id: Optional[uuid.UUID] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
):
    """This organization's own audit trail, newest first.

    Scoped to ``org`` from the caller's own row, like every other fleet query —
    and doubly worth stating here, since a leak from this table would name the
    records another company had deleted.

    Support reads by the platform operator are excluded: they are recorded
    against the organization for *our* accountability and answering them belongs
    on the platform view, not in a customer's activity feed where they would
    read as their own staff's actions.
    """
    stmt = (
        select(AuditEvent)
        .where(
            AuditEvent.target_org_id == org,
            AuditEvent.target_type.is_not(None),
        )
        .order_by(desc(AuditEvent.created_at))
        .limit(limit)
    )
    if action:
        stmt = stmt.where(AuditEvent.action == action)
    if target_type:
        stmt = stmt.where(AuditEvent.target_type == target_type)
    if target_id:
        stmt = stmt.where(AuditEvent.target_id == target_id)

    return (await db.execute(stmt)).scalars().all()
