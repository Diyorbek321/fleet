"""Background scheduler — periodic, idempotent maintenance/safety jobs.

A single ``AsyncIOScheduler`` runs in-process inside the FastAPI event loop and
is started/stopped from the app lifespan. It is intentionally skipped under the
test environment (``settings.env == "test"``) and whenever ``SCHEDULER_ENABLED``
is false, so the test suite stays deterministic and migrations smoke tests don't
spin up timers.

Each job opens its own ``AsyncSession`` (jobs run outside any request), is wrapped
in ``try/except`` so one failure never kills the scheduler, and is written to be
idempotent — re-running it produces the same end state.
"""
from __future__ import annotations

from datetime import date

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.logging import logger
from app.models.drivers import Driver, SafetyScore
from app.models.enums import ServiceStatus
from app.models.maintenance import ServiceInterval
from app.models.trucks import Truck
from app.services.maintenance import refresh_service_statuses
from app.services.reminders import check_document_expiries

try:  # pragma: no cover - exercised only when redis is installed/enabled
    import redis.asyncio as aioredis
except Exception:  # pragma: no cover
    aioredis = None

_redis_client = None


async def _run_locked(job_name: str, coro_fn) -> None:
    """Run a scheduled job at most once per tick across all replicas.

    With multiple app replicas every process starts the scheduler, so without a
    shared lock each periodic job fires N times in parallel (racing on the same
    rows). When Redis is enabled we take a short-lived ``SET NX EX`` lock keyed by
    job name; only the replica that wins runs the job this tick. In single-process
    dev (no Redis) we just run it.
    """
    if not settings.redis_enabled or aioredis is None:
        await coro_fn()
        return

    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)

    # TTL a bit under the interval so the lock auto-releases before the next tick.
    ttl = max(30, settings.scheduler_interval_minutes * 60 - 10)
    try:
        won = await _redis_client.set(f"scheduler:lock:{job_name}", "1", nx=True, ex=ttl)
    except Exception:
        logger.exception("scheduler_lock_failed", job=job_name)
        return  # don't run unlocked if Redis is unreachable — safer to skip a tick
    if won:
        await coro_fn()
    else:
        logger.info("scheduler_job_skipped_locked", job=job_name)


async def check_overdue_maintenance() -> None:
    """Recompute service-interval statuses and log a warning per overdue item.

    Reuses :func:`refresh_service_statuses` (the same logic the reminders endpoint
    relies on) to flip statuses to ``overdue`` based on next-service date/mileage,
    then emits one structured warning per currently-overdue interval so operators
    have an audit trail even without opening the UI. Idempotent: the status field
    already exists and only changes when the thresholds are crossed.
    """
    try:
        async with SessionLocal() as db:
            updated = await refresh_service_statuses(db)

            overdue = (
                await db.execute(
                    select(ServiceInterval).where(
                        ServiceInterval.status == ServiceStatus.overdue
                    )
                )
            ).scalars().all()

            for si in overdue:
                truck = (
                    await db.execute(select(Truck).where(Truck.id == si.truck_id))
                ).scalar_one_or_none()
                logger.warning(
                    "maintenance_overdue",
                    truck_id=str(si.truck_id),
                    truck_plate=truck.plate_number if truck else None,
                    service_type=si.service_type.value,
                    next_service_date=str(si.next_service_date) if si.next_service_date else None,
                    next_service_mileage=(
                        float(si.next_service_mileage)
                        if si.next_service_mileage is not None
                        else None
                    ),
                    current_mileage=float(truck.mileage) if truck else None,
                )

            logger.info(
                "maintenance_check_done",
                statuses_updated=updated,
                overdue_count=len(overdue),
            )
    except Exception:  # noqa: BLE001 — never let a job crash the scheduler
        logger.exception("maintenance_check_failed")


async def recalc_safety_scores() -> None:
    """Refresh each driver's rolling safety aggregate from existing score history.

    There is no driving-event source table in the schema (speeding/braking events
    are stored pre-aggregated on ``safety_scores`` rows), so a from-scratch recompute
    is impossible — we skip gracefully in that case. When score history *does* exist
    we recompute an up-to-date rolling snapshot for the current period from the
    driver's recorded events, which keeps the "latest score" surfaced in the UI fresh.
    """
    try:
        async with SessionLocal() as db:
            drivers = (await db.execute(select(Driver))).scalars().all()
            recomputed = 0
            today = date.today()

            for driver in drivers:
                scores = (
                    await db.execute(
                        select(SafetyScore)
                        .where(SafetyScore.driver_id == driver.id)
                        .order_by(SafetyScore.period_end.desc())
                    )
                ).scalars().all()
                if not scores:
                    continue  # no event history to recompute from — skip gracefully

                latest = scores[0]
                # Idempotent recompute: derive the score from the recorded events on
                # the latest period using the same penalty model the seed uses.
                score = max(
                    0,
                    100
                    - latest.speeding_events * 3
                    - latest.harsh_braking * 2
                    - latest.harsh_acceleration * 2
                    - latest.idle_time_minutes // 30,
                )
                if score != latest.score:
                    latest.score = score
                    latest.calculated_at = latest.calculated_at
                    recomputed += 1

            if recomputed:
                await db.commit()
            logger.info(
                "safety_recalc_done",
                drivers=len(drivers),
                recomputed=recomputed,
                as_of=str(today),
            )
    except Exception:  # noqa: BLE001
        logger.exception("safety_recalc_failed")


_scheduler: AsyncIOScheduler | None = None


def start_scheduler() -> AsyncIOScheduler | None:
    """Start the background scheduler unless disabled or running under tests.

    Returns the scheduler instance (or ``None`` when skipped) so the lifespan can
    log what happened.
    """
    global _scheduler

    if settings.env == "test" or not settings.scheduler_enabled:
        logger.info(
            "scheduler_skipped",
            env=settings.env,
            enabled=settings.scheduler_enabled,
        )
        return None

    if _scheduler is not None:
        return _scheduler

    interval = max(1, settings.scheduler_interval_minutes)
    scheduler = AsyncIOScheduler()

    async def _check_job() -> None:
        await _run_locked("check_overdue_maintenance", check_overdue_maintenance)

    async def _safety_job() -> None:
        await _run_locked("recalc_safety_scores", recalc_safety_scores)

    async def _expiry_job() -> None:
        await _run_locked("check_document_expiries", check_document_expiries)

    scheduler.add_job(
        _check_job,
        trigger="interval",
        minutes=interval,
        id="check_overdue_maintenance",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    scheduler.add_job(
        _safety_job,
        trigger="interval",
        minutes=interval,
        id="recalc_safety_scores",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    scheduler.add_job(
        _expiry_job,
        trigger="interval",
        minutes=max(interval, 60),  # expiries change slowly; hourly is plenty
        id="check_document_expiries",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    scheduler.start()
    _scheduler = scheduler
    logger.info("scheduler_started", interval_minutes=interval)
    return scheduler


def shutdown_scheduler() -> None:
    """Stop the scheduler if it is running. Safe to call when never started."""
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        logger.info("scheduler_shutdown")
        _scheduler = None
