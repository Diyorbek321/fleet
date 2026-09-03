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
from functools import partial
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.logging import logger
from app.models.drivers import Driver, SafetyScore
from app.models.enums import ServiceStatus
from app.models.maintenance import ServiceInterval
from app.models.trucks import Truck
from app.services.cgr import get_cgr_client
from app.services.daily_updates import send_daily_trip_updates
from app.services.gps_retention import purge_expired_history
from app.services.maintenance import refresh_service_statuses
from app.services.owner_alerts import prune_notification_log
from app.services.owner_alerts import briefing as owner_briefing
from app.services.owner_alerts import cash as owner_cash
from app.services.owner_alerts import expiry as owner_expiry
from app.services.owner_alerts import leakage as owner_leakage
from app.services.owner_alerts import reports as owner_reports
from app.services.owner_alerts import trips as owner_trips
from app.services.queue import poll_active_watches
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


# How many consecutive sweeps may find nothing, while trucks are actively being
# watched, before we treat it as a breakage rather than a quiet day. At the
# default 15-minute interval this is two hours — long enough that a genuine lull
# does not page anyone, short enough to catch the site changing shape the same
# working day.
_EMPTY_POLL_ALERT_THRESHOLD = 8

# Reset by any sweep that resolves at least one booking, and by a restart.
_consecutive_empty_polls = 0


async def poll_queue_watches() -> None:
    """Refresh every active CarGoRuqsat border-queue watch against the public registry.

    Reuses :func:`poll_active_watches` (the same evaluate+notify logic the manager
    panel's refresh uses) so drivers get notified of status changes without anyone
    opening the app. Errors are swallowed/logged so a flaky external site never
    crashes the scheduler.

    Also watches for the failure this integration actually suffers. Scraping
    another site's HTML breaks silently: the markup changes, every lookup parses
    to "no booking", and drivers stop being told anything while the logs stay
    clean and no exception is ever raised. A run of sweeps that resolve nothing
    at all, with watches active, is the only visible symptom — so escalate it
    instead of logging another cheerful "done".
    """
    global _consecutive_empty_polls
    try:
        async with SessionLocal() as db:
            client = get_cgr_client()
            result = await poll_active_watches(db, client)
            logger.info(
                "queue_poll_done",
                watched=result.watched,
                found=result.found,
                changed=result.changed,
            )

            if result.watched == 0:
                return  # nothing to infer from a sweep with no watches

            if result.found:
                _consecutive_empty_polls = 0
                return

            _consecutive_empty_polls += 1
            if _consecutive_empty_polls >= _EMPTY_POLL_ALERT_THRESHOLD:
                # error, not warning: this is a customer-facing outage, and it
                # needs to reach Sentry rather than sit in the log stream.
                logger.error(
                    "queue_poll_no_bookings_found",
                    consecutive_empty_polls=_consecutive_empty_polls,
                    watched=result.watched,
                    hint=(
                        "no watched truck has resolved to a booking for several "
                        "sweeps — the public registry may have changed shape; "
                        "run `pytest -m live tests/test_cgr.py`"
                    ),
                )
    except Exception:  # noqa: BLE001 — never let a job crash the scheduler
        logger.exception("queue_poll_failed")


async def purge_gps_history() -> None:
    """Delete raw position history past the retention window.

    ``truck_location_history`` is the only unbounded table in the schema — one
    row per ping, ~2 400 per truck per driving day. Without this the droplet's
    disk is the deadline. Batched and idempotent: whatever a run doesn't finish
    is picked up by the next one.
    """
    try:
        async with SessionLocal() as db:
            removed = await purge_expired_history(db)
            logger.info("gps_retention_done", rows_removed=removed)
    except Exception:  # noqa: BLE001 — never let a job crash the scheduler
        logger.exception("gps_retention_failed")


async def _run_owner_watch(name: str, run_fn) -> None:
    """Run one owner-alert watcher on its own session.

    Every module in ``app.services.owner_alerts`` exposes the same
    ``run(db) -> int`` entry point and already contains its own failures, so
    one wrapper serves all of them rather than seven near-identical jobs. The
    try/except is still here because "never raises" is a promise about the
    watcher's own logic, not about the session it was handed — a connection
    dropped mid-tick surfaces here, and must not take the scheduler with it.
    """
    try:
        async with SessionLocal() as db:
            sent = await run_fn(db)
            logger.info("owner_alert_watch_done", watch=name, alerts_sent=sent)
    except Exception:  # noqa: BLE001 — never let a job crash the scheduler
        logger.exception("owner_alert_watch_failed", watch=name)


async def prune_owner_alert_log() -> None:
    """Drop dedupe rows too old to suppress anything.

    ``notification_log`` gains a row per alert delivered and nothing else ever
    removes one, so it is the second unbounded table here. A row older than
    every TTL in use can no longer change a decision, which makes deleting it
    free — and daily is often enough for a table that grows by alerts, not pings.
    """
    try:
        async with SessionLocal() as db:
            removed = await prune_notification_log(db)
            logger.info("owner_alert_log_pruned", rows_removed=removed)
    except Exception:  # noqa: BLE001 — never let a job crash the scheduler
        logger.exception("owner_alert_log_prune_failed")


# Every watcher and the floor on how often it is worth looking. The scheduler's
# own interval still wins whenever it is coarser, so a deployment that ticks
# hourly gets hourly watchers rather than a backlog of overlapping runs.
_OWNER_ALERT_WATCHES: tuple[tuple[str, Any, int], ...] = (
    # A load running late and a driver's cash not adding up are only ever found
    # by looking, and the bus dedupes a repeat finding for free — so these three
    # ride the plain tick.
    ("owner_alert_trips", owner_trips.run, 0),
    ("owner_alert_cash", owner_cash.run, 0),
    ("owner_alert_leakage", owner_leakage.run, 0),
    # Expiries move by the day, and the watcher's own scan is written for an
    # hourly cadence.
    ("owner_alert_expiry", owner_expiry.run, 60),
    # Both self-gate on the clock/calendar and no-op otherwise, exactly like
    # send_daily_trip_updates. A sub-hour tick is what leaves margin around the
    # target hour, since a restart spanning it is the one way a day is missed.
    ("owner_alert_briefing", owner_briefing.run, 15),
    ("owner_alert_reports", owner_reports.run, 15),
)


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

    async def _queue_poll_job() -> None:
        await _run_locked("poll_queue_watches", poll_queue_watches)

    async def _gps_retention_job() -> None:
        await _run_locked("purge_gps_history", purge_gps_history)

    async def _daily_updates_job() -> None:
        # The job itself self-gates on the configured hour of day, so it's
        # safe (and cheap) to invoke on every scheduler tick.
        await _run_locked("send_daily_trip_updates", send_daily_trip_updates)

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
    scheduler.add_job(
        _queue_poll_job,
        trigger="interval",
        minutes=max(interval, 5),  # border-queue status shifts on the order of minutes
        id="poll_queue_watches",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    scheduler.add_job(
        _gps_retention_job,
        trigger="interval",
        # Six-hourly: retention is measured in days, so there is nothing to gain
        # from running it often, and each run is the heaviest write job here.
        minutes=max(interval, 360),
        id="purge_gps_history",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    # Runs frequently but only actually sends when the current UTC hour
    # matches ``TELEGRAM_DAILY_HOUR_UTC``. Sub-hour interval gives ~15 min
    # margin around the target hour on restarts / clock drift.
    scheduler.add_job(
        _daily_updates_job,
        trigger="interval",
        minutes=max(interval, 15),
        id="send_daily_trip_updates",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )

    for watch_name, watch_run, floor_minutes in _OWNER_ALERT_WATCHES:
        # Both loop variables are bound as defaults: a closure over them would
        # leave all six jobs running whichever watcher the loop ended on.
        async def _watch_job(name: str = watch_name, run_fn: Any = watch_run) -> None:
            await _run_locked(name, partial(_run_owner_watch, name, run_fn))

        scheduler.add_job(
            _watch_job,
            trigger="interval",
            minutes=max(interval, floor_minutes),
            id=watch_name,
            max_instances=1,
            coalesce=True,
            replace_existing=True,
        )

    async def _owner_alert_prune_job() -> None:
        await _run_locked("prune_owner_alert_log", prune_owner_alert_log)

    scheduler.add_job(
        _owner_alert_prune_job,
        trigger="interval",
        # Rows age out in days, so daily clears them long before the table
        # matters — and keeps the delete off the ticks the watchers share.
        minutes=max(interval, 1440),
        id="prune_owner_alert_log",
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
