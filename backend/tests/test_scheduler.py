"""Background scheduler: skips under tests, jobs run idempotently."""
from __future__ import annotations

import uuid
from datetime import date, timedelta

from httpx import AsyncClient

from app.core.database import SessionLocal
from app.models.enums import ServiceStatus, ServiceType
from app.models.maintenance import ServiceInterval
from app.models.trucks import Truck
from app.services.scheduler import (
    check_overdue_maintenance,
    recalc_safety_scores,
    start_scheduler,
)


def test_scheduler_skipped_under_test_env():
    """The scheduler must not start when ENV=test (set in conftest)."""
    assert start_scheduler() is None


def _watcher_run_entry_points() -> dict[str, object]:
    """Every ``app.services.owner_alerts`` module exposing the package's ``run(db)``.

    Discovered by import rather than listed here on purpose — a list would have
    to be edited by the same person who forgot the scheduler entry.
    """
    import importlib
    import pkgutil

    import app.services.owner_alerts as pkg

    found: dict[str, object] = {}
    for info in pkgutil.iter_modules(pkg.__path__):
        module = importlib.import_module(f"{pkg.__name__}.{info.name}")
        run = getattr(module, "run", None)
        # Defined here, not imported from a sibling: re-exports are not watchers.
        if callable(run) and getattr(run, "__module__", None) == module.__name__:
            found[info.name] = run
    return found


async def test_every_owner_alert_watcher_is_actually_scheduled(monkeypatch):
    """A watcher nothing calls is dead code that still passes its own tests.

    All six shipped this way: each had a green suite driving ``run(db)`` directly
    while no job registered them, so no owner would ever have received an alert.
    Asserting against the started scheduler — not against the table feeding it —
    is what makes this catch a watcher that is listed but never registered.
    """
    from app.core.config import settings
    from app.services import scheduler as sched

    watchers = _watcher_run_entry_points()
    assert watchers, "discovered no watchers at all — this probe is broken, not the code"

    listed = {run_fn for _, run_fn, _ in sched._OWNER_ALERT_WATCHES}
    missing = {name for name, run in watchers.items() if run not in listed}
    assert not missing, f"watchers written but never scheduled: {sorted(missing)}"

    # The env gate above is the whole reason this needs lifting; leave the
    # module-level handle clear so a real deployment's scheduler is untouched.
    monkeypatch.setattr(settings, "env", "dev")
    monkeypatch.setattr(settings, "scheduler_enabled", True)
    monkeypatch.setattr(sched, "_scheduler", None)

    scheduler = sched.start_scheduler()
    try:
        assert scheduler is not None
        registered = {job.id for job in scheduler.get_jobs()}
    finally:
        sched.shutdown_scheduler()

    for name, _, _ in sched._OWNER_ALERT_WATCHES:
        assert name in registered, f"{name} is listed but no job runs it"
    assert "prune_owner_alert_log" in registered, (
        "notification_log is append-only; without the sweep it grows forever"
    )


async def test_maintenance_job_flags_overdue_interval(client: AsyncClient, admin_headers):
    # Create a truck whose mileage is already past a service interval threshold.
    truck = (
        await client.post(
            "/api/trucks",
            headers=admin_headers,
            json={"name": "Sched", "plate_number": "SCH-1"},
        )
    ).json()

    async with SessionLocal() as db:
        t = await db.get(Truck, uuid.UUID(truck["id"]))
        t.mileage = 100000
        db.add(
            ServiceInterval(
                truck_id=t.id,
                service_type=ServiceType.oil_change,
                next_service_mileage=50000,
                next_service_date=date.today() - timedelta(days=5),
                status=ServiceStatus.scheduled,
            )
        )
        await db.commit()

    # Job is idempotent and should mark the interval overdue.
    await check_overdue_maintenance()
    await check_overdue_maintenance()

    async with SessionLocal() as db:
        from sqlalchemy import select

        si = (await db.execute(select(ServiceInterval))).scalar_one()
        assert si.status == ServiceStatus.overdue


async def test_safety_recalc_runs_without_history(client: AsyncClient, admin_headers):
    # A driver with no safety-score history -> job skips gracefully (no error).
    await client.post(
        "/api/drivers",
        headers=admin_headers,
        json={"name": "NoEvents", "license_number": "LIC-SCH-1"},
    )
    await recalc_safety_scores()  # must not raise


# ── border-queue poll: detecting a silent scraper breakage ───────────────────
#
# The CarGoRuqsat integration reads someone else's HTML, and when that breaks it
# does not raise: every lookup parses to "no booking" and drivers simply stop
# being told anything. These cover the only signal that distinguishes it from a
# quiet day — repeated sweeps that resolve nothing while watches are active.

async def _run_poll(monkeypatch, results):
    """Drive poll_queue_watches over a canned sequence of PollResults."""
    from app.services import scheduler as sched
    from app.services.queue import PollResult

    calls = iter(results)

    async def fake_poll(db, client):
        return next(calls)

    monkeypatch.setattr(sched, "poll_active_watches", fake_poll)
    monkeypatch.setattr(sched, "_consecutive_empty_polls", 0, raising=False)

    logged: list[tuple[str, dict]] = []
    for level in ("info", "error"):
        def record(event, _level=level, **kw):
            logged.append((_level, {"event": event, **kw}))
        monkeypatch.setattr(sched.logger, level, record)

    for _ in results:
        await sched.poll_queue_watches()
    return logged, PollResult


async def test_empty_polls_below_the_threshold_stay_quiet(monkeypatch):
    from app.services.queue import PollResult
    from app.services import scheduler as sched

    logged, _ = await _run_poll(
        monkeypatch,
        [PollResult(watched=3, found=0, changed=0)] * (sched._EMPTY_POLL_ALERT_THRESHOLD - 1),
    )
    assert not [e for lvl, e in logged if lvl == "error"]


async def test_a_run_of_empty_polls_is_escalated(monkeypatch):
    from app.services.queue import PollResult
    from app.services import scheduler as sched

    logged, _ = await _run_poll(
        monkeypatch,
        [PollResult(watched=3, found=0, changed=0)] * sched._EMPTY_POLL_ALERT_THRESHOLD,
    )
    errors = [e for lvl, e in logged if lvl == "error"]
    assert len(errors) == 1
    assert errors[0]["event"] == "queue_poll_no_bookings_found"
    assert errors[0]["watched"] == 3


async def test_a_single_booking_resets_the_streak(monkeypatch):
    """One truck resolving proves the scraper still works; the count starts over."""
    from app.services.queue import PollResult
    from app.services import scheduler as sched

    n = sched._EMPTY_POLL_ALERT_THRESHOLD
    logged, _ = await _run_poll(
        monkeypatch,
        [PollResult(watched=3, found=0, changed=0)] * (n - 1)
        + [PollResult(watched=3, found=1, changed=0)]
        + [PollResult(watched=3, found=0, changed=0)] * (n - 1),
    )
    assert not [e for lvl, e in logged if lvl == "error"]


async def test_no_active_watches_is_not_a_breakage(monkeypatch):
    """An empty sweep says nothing about the scraper when nobody is watching."""
    from app.services.queue import PollResult
    from app.services import scheduler as sched

    logged, _ = await _run_poll(
        monkeypatch,
        [PollResult(watched=0, found=0, changed=0)] * (sched._EMPTY_POLL_ALERT_THRESHOLD * 2),
    )
    assert not [e for lvl, e in logged if lvl == "error"]
