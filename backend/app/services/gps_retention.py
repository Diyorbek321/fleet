"""Retention for raw GPS history.

``truck_location_history`` is the only table in the schema that grows without
bound: one row per position ping, ~2 400 per truck per driving day. Nothing ever
deleted it, so a 20-truck fleet added ~1.4M rows a month until the droplet's
disk (or the analytics scan) gave out first.

This module deletes rows older than the configured retention window. It is run
by the scheduler, but is written as a plain function so it can also be invoked
from a one-off script or a test.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger
from app.models.trucks import TruckLocationHistory

# Hard stop so a single run can never spin forever on a pathological table;
# whatever is left is picked up by the next scheduled run.
MAX_BATCHES_PER_RUN = 200


async def purge_location_history(
    db: AsyncSession,
    retention_days: int,
    batch_size: int = 10_000,
    *,
    now: datetime | None = None,
) -> int:
    """Delete history rows older than ``retention_days``. Returns rows removed.

    Deletes in batches rather than one big statement: the first run against a
    table that has already grown to millions of rows would otherwise hold a lock
    for minutes and write a single enormous WAL record. Each batch is committed
    on its own, so an interrupted run still makes progress.

    ``retention_days <= 0`` disables purging entirely (returns 0) — the escape
    hatch for deployments that want to keep every point forever.
    """
    if retention_days <= 0:
        return 0

    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=retention_days)
    batch_size = max(1, batch_size)
    total = 0

    for _ in range(MAX_BATCHES_PER_RUN):
        # Sub-select the ids first: a bare `DELETE ... WHERE recorded_at < x`
        # cannot be LIMITed in Postgres, and deleting by primary key lets the
        # planner use ix_truck_location_history_recorded_at for the lookup.
        doomed = (
            select(TruckLocationHistory.id)
            .where(TruckLocationHistory.recorded_at < cutoff)
            .limit(batch_size)
            .scalar_subquery()
        )
        result = await db.execute(
            delete(TruckLocationHistory).where(TruckLocationHistory.id.in_(doomed))
        )
        await db.commit()

        removed = result.rowcount or 0
        total += removed
        if removed < batch_size:
            break

    return total


async def purge_expired_history(db: AsyncSession) -> int:
    """Settings-driven wrapper used by the scheduler."""
    from app.core.config import settings

    removed = await purge_location_history(
        db,
        retention_days=settings.gps_history_retention_days,
        batch_size=settings.gps_purge_batch_size,
    )
    if removed:
        logger.info(
            "gps_history_purged",
            rows=removed,
            retention_days=settings.gps_history_retention_days,
        )
    return removed
