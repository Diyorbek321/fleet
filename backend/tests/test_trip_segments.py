"""Trip segmentation: moving vs stopped stretches from GPS history."""
from __future__ import annotations

import itertools
from datetime import datetime, timedelta, timezone

from httpx import AsyncClient


async def _create_truck(client: AsyncClient, headers: dict, plate: str = "SEG-1") -> str:
    res = await client.post(
        "/api/trucks", headers=headers, json={"name": "SegTruck", "plate_number": plate}
    )
    return res.json()["id"]


# IMEIs are unique platform-wide, so each enrollment in this module needs its
# own. Tests here share a database, so a fixed constant would collide on the
# second test rather than fail where the collision belongs.
_imei_counter = itertools.count(1)


async def _ingest(
    client: AsyncClient, headers: dict, truck_id: str, points: list[dict]
) -> None:
    """Seed GPS history the way a real tracker does — enrolled, keyed, scoped.

    There is no fleet-wide key to borrow any more: one belonged to no
    organization, so ingest could not check that the truck being written to was
    the caller's. Enrolling a device is now the only way in, here as in prod.
    """
    imei = f"35209408700{next(_imei_counter):04d}"
    enrolled = await client.post(
        "/api/devices", headers=headers, json={"imei": imei, "truck_id": truck_id}
    )
    assert enrolled.status_code in (200, 201), enrolled.text
    api_key = enrolled.json()["api_key"]

    res = await client.post(
        "/api/gps/ingest",
        headers={"X-API-Key": api_key, "X-IMEI": imei},
        json={"points": points},
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
    await _ingest(client, admin_headers, truck_id, points)

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
        admin_headers,
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
        admin_headers,
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
