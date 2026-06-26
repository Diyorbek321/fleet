"""Manager panel for CarGoRuqsat border-queue watches (`/api/queue`).

Lists each driver's standing border-queue watch for the caller's org and lets a
manager force a refresh against the public registry. Org-scoped + staff-only.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.logging import logger
from app.deps.auth import get_org_id, require_role
from app.models.driver_app import QueueWatch
from app.models.drivers import Driver
from app.models.enums import UserRole
from app.schemas.queue import OrgQueueRowOut
from app.services.cgr import CgrClient, get_cgr_client
from app.services.queue import evaluate_watch, notify_queue_change

router = APIRouter(prefix="/api/queue", tags=["Queue"])

# Only non-driver staff may view/refresh the org's border-queue panel.
_STAFF = require_role(UserRole.admin, UserRole.manager, UserRole.operator)


def _to_row(watch: QueueWatch, driver_name: str) -> OrgQueueRowOut:
    return OrgQueueRowOut(
        watch_id=watch.id,
        driver_id=watch.driver_id,
        driver_name=driver_name,
        plate=watch.plate,
        checkpoint=watch.checkpoint,
        country=watch.country,
        active=watch.active,
        last_status=watch.last_status,
        last_seen_queue_at=watch.last_seen_queue_at,
        updated_at=watch.updated_at,
    )


async def _active_watches(db: AsyncSession, org: uuid.UUID) -> list[tuple[QueueWatch, str]]:
    """Active watches for the org joined with the driver's name."""
    res = await db.execute(
        select(QueueWatch, Driver.name)
        .join(Driver, Driver.id == QueueWatch.driver_id)
        .where(Driver.org_id == org, QueueWatch.active.is_(True))
    )
    return [(watch, name) for watch, name in res.all()]


@router.get("", response_model=list[OrgQueueRowOut])
async def list_queue(
    db: AsyncSession = Depends(get_db),
    org: uuid.UUID = Depends(get_org_id),
    _user=Depends(_STAFF),
):
    """Every active border-queue watch for the caller's org."""
    rows = await _active_watches(db, org)
    return [_to_row(watch, name) for watch, name in rows]


@router.post("/refresh", response_model=list[OrgQueueRowOut])
async def refresh_queue(
    db: AsyncSession = Depends(get_db),
    org: uuid.UUID = Depends(get_org_id),
    client: CgrClient = Depends(get_cgr_client),
    _user=Depends(_STAFF),
):
    """Re-check the org's active watches against the public registry, then return them.

    Each watch is refreshed in isolation so one failing external lookup does not
    abort the others.
    """
    rows = await _active_watches(db, org)
    for watch, _name in rows:
        try:
            record, notify = await evaluate_watch(watch, client)
            if notify:
                await notify_queue_change(db, watch, record)
        except Exception:  # noqa: BLE001 — one bad lookup must not abort the refresh
            logger.exception(
                "queue_refresh_failed",
                extra={"watch_id": str(watch.id), "plate": watch.plate},
            )
    await db.commit()
    return [_to_row(watch, name) for watch, name in rows]
