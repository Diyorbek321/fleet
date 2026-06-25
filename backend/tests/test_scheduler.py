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
