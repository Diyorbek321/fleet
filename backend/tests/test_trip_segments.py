"""Trip segmentation: moving vs stopped stretches from GPS history."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from httpx import AsyncClient


async def _create_truck(client: AsyncClient, headers: dict, plate: str = "SEG-1") -> str:
    res = await client.post(
        "/api/trucks", headers=headers, json={"name": "SegTruck", "plate_number": plate}
    )
    return res.json()["id"]


async def _ingest(client: AsyncClient, truck_id: str, points: list[dict]) -> None:
    """Seed GPS history via the legacy fleet API key (configured in conftest)."""
    res = await client.post(
        "/api/gps/ingest",
        headers={"X-API-Key": "legacy-test-key"},
        json={"points": [{"truck_id": truck_id, **p} for p in points]},
    )
    assert res.status_code == 200, res.text


async def test_segments_split_moving_and_stopped(client: AsyncClient, admin_headers):
    truck_id = await _create_truck(client, admin_headers)
    base = datetime(2026, 6, 24, 8, 0, tzinfo=timezone.utc)

    # 3 moving points, then 2 stopped, then 1 moving again -> 3 segments.
    points = [
        {"latitude": 41.30, "longitude": 69.20, "speed": 40, "recorded_at": (base + timedelta(minutes=0)).isoformat()},
        {"latitude": 41.31, "longitude": 69.21, "speed": 45, "recorded_at": (base + timedelta(minutes=5)).isoformat()},
        {"latitude": 41.32, "longitude": 69.22, "speed": 50, "recorded_at": (base + timedelta(minutes=10)).isoformat()},
        {"latitude": 41.32, "longitude": 69.22, "speed": 0, "recorded_at": (base + timedelta(minutes=15)).isoformat()},
        {"latitude": 41.32, "longitude": 69.22, "speed": 0, "recorded_at": (base + timedelta(minutes=45)).isoformat()},
        {"latitude": 41.33, "longitude": 69.23, "speed": 30, "recorded_at": (base + timedelta(minutes=50)).isoformat()},
    ]
    await _ingest(client, truck_id, points)

    trip = (
        await client.post(
            "/api/trips", headers=admin_headers, json={"truck_id": truck_id, "rate": 1000000}
        )
    ).json()
    tid = trip["id"]

    # Recompute from GPS history and store.
    res = await client.post(f"/api/trips/{tid}/segments", headers=admin_headers)
    assert res.status_code == 200, res.text
    segs = res.json()

    kinds = [s["kind"] for s in segs]
    assert kinds == ["moving", "stopped", "moving"]
    # Sequencing is contiguous and ordered.
    assert [s["seq"] for s in segs] == [0, 1, 2]
    # The stopped segment spans 30 minutes (15 -> 45).
    assert segs[1]["duration_s"] == 30 * 60
    assert segs[1]["point_count"] == 2
    # Moving segments cover distance; the stopped one does not move meaningfully.
    assert segs[0]["distance_km"] > 0
    assert segs[1]["distance_km"] == 0


async def test_get_segments_returns_stored_then_recompute(client: AsyncClient, admin_headers):
    truck_id = await _create_truck(client, admin_headers, plate="SEG-2")
    base = datetime(2026, 6, 24, 9, 0, tzinfo=timezone.utc)
    await _ingest(
        client,
        truck_id,
        [
            {"latitude": 40.0, "longitude": 65.0, "speed": 60, "recorded_at": base.isoformat()},
            {"latitude": 40.1, "longitude": 65.1, "speed": 60, "recorded_at": (base + timedelta(minutes=10)).isoformat()},
        ],
    )
    trip = (
        await client.post(
            "/api/trips", headers=admin_headers, json={"truck_id": truck_id, "rate": 1}
        )
    ).json()
    tid = trip["id"]

    # No stored segments yet.
    empty = await client.get(f"/api/trips/{tid}/segments", headers=admin_headers)
    assert empty.status_code == 200
    assert empty.json() == []

    # recompute=true computes + persists.
    computed = await client.get(
        f"/api/trips/{tid}/segments?recompute=true", headers=admin_headers
    )
    assert computed.status_code == 200
    assert len(computed.json()) == 1
    assert computed.json()[0]["kind"] == "moving"

    # Now stored segments are returned without recompute.
    stored = await client.get(f"/api/trips/{tid}/segments", headers=admin_headers)
    assert len(stored.json()) == 1


async def test_segments_idempotent(client: AsyncClient, admin_headers):
    truck_id = await _create_truck(client, admin_headers, plate="SEG-3")
    base = datetime(2026, 6, 24, 10, 0, tzinfo=timezone.utc)
    await _ingest(
        client,
        truck_id,
        [
            {"latitude": 40.0, "longitude": 65.0, "speed": 50, "recorded_at": base.isoformat()},
            {"latitude": 40.1, "longitude": 65.1, "speed": 50, "recorded_at": (base + timedelta(minutes=5)).isoformat()},
        ],
    )
    trip = (
        await client.post(
            "/api/trips", headers=admin_headers, json={"truck_id": truck_id, "rate": 1}
        )
    ).json()
    tid = trip["id"]

    first = (await client.post(f"/api/trips/{tid}/segments", headers=admin_headers)).json()
    second = (await client.post(f"/api/trips/{tid}/segments", headers=admin_headers)).json()
    # Re-running yields the same number of segments (no duplication).
    assert len(first) == len(second) == 1


async def test_segments_requires_auth(client: AsyncClient, admin_headers):
    truck_id = await _create_truck(client, admin_headers, plate="SEG-4")
    trip = (
        await client.post(
            "/api/trips", headers=admin_headers, json={"truck_id": truck_id, "rate": 1}
        )
    ).json()
    res = await client.get(f"/api/trips/{trip['id']}/segments")
    assert res.status_code == 401
