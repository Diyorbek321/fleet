"""GPS history retention.

``truck_location_history`` is the only table in the schema that grows without
bound — one row per position ping, ~2 400 per truck per driving day. These tests
pin the purge's contract: old rows go, recent rows stay, and the job is safe to
run repeatedly.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.trucks import TruckLocationHistory
from app.services.gps_retention import purge_location_history

BASE_LAT = 41.31
BASE_LNG = 69.24


async def _create_truck(client: AsyncClient, headers: dict, plate: str) -> str:
    res = await client.post(
        "/api/trucks", headers=headers, json={"name": f"Truck {plate}", "plate_number": plate}
    )
    return res.json()["id"]


async def _seed_history(db: AsyncSession, truck_id: str, ages_days: list[float]) -> None:
    now = datetime.now(timezone.utc)
    for age in ages_days:
        db.add(
            TruckLocationHistory(
                truck_id=uuid.UUID(truck_id),
                latitude=BASE_LAT,
                longitude=BASE_LNG,
                speed=0,
                recorded_at=now - timedelta(days=age),
            )
        )
    await db.commit()


async def _count(db: AsyncSession) -> int:
    return (await db.execute(select(func.count(TruckLocationHistory.id)))).scalar() or 0


async def test_purge_removes_only_points_older_than_the_window(
    client: AsyncClient, admin_headers, db: AsyncSession
):
    truck_id = await _create_truck(client, admin_headers, "PURGE-01")
    await _seed_history(db, truck_id, [1, 10, 89, 91, 200])

    removed = await purge_location_history(db, retention_days=90)

    assert removed == 2  # the 91- and 200-day-old points
    assert await _count(db) == 3


async def test_purge_is_idempotent(client: AsyncClient, admin_headers, db: AsyncSession):
    """The scheduler runs this every six hours forever; a second pass must be a
    no-op rather than eating into the retained window."""
    truck_id = await _create_truck(client, admin_headers, "PURGE-02")
    await _seed_history(db, truck_id, [1, 100, 120])

    first = await purge_location_history(db, retention_days=90)
    second = await purge_location_history(db, retention_days=90)

    assert first == 2
    assert second == 0
    assert await _count(db) == 1


async def test_retention_of_zero_disables_purging(
    client: AsyncClient, admin_headers, db: AsyncSession
):
    """The escape hatch for deployments that want every point kept forever."""
    truck_id = await _create_truck(client, admin_headers, "PURGE-03")
    await _seed_history(db, truck_id, [500, 900])

    assert await purge_location_history(db, retention_days=0) == 0
    assert await _count(db) == 2


async def test_purge_deletes_everything_due_across_multiple_batches(
    client: AsyncClient, admin_headers, db: AsyncSession
):
    """Batching exists so the first run on a multi-million-row table doesn't take
    a long lock. It must still finish the job, not stop after one batch."""
    truck_id = await _create_truck(client, admin_headers, "PURGE-04")
    await _seed_history(db, truck_id, [100 + i for i in range(25)] + [1, 2])

    removed = await purge_location_history(db, retention_days=90, batch_size=10)

    assert removed == 25
    assert await _count(db) == 2
