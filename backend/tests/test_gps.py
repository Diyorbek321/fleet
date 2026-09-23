"""GPS ingest: device auth, batch handling, truck status derivation."""
from __future__ import annotations

import contextlib

import pytest
import sqlalchemy as sa
from httpx import AsyncClient

from app.core.database import engine
from app.core.ws import ws_manager


async def _create_truck(client: AsyncClient, headers: dict) -> str:
    res = await client.post(
        "/api/trucks", headers=headers, json={"name": "Alpha", "plate_number": "AA-01"}
    )
    return res.json()["id"]


async def _enroll_device(
    client: AsyncClient, headers: dict, imei: str, truck_id: str | None = None
) -> tuple[str, str]:
    body: dict = {"imei": imei}
    if truck_id:
        body["truck_id"] = truck_id
    res = await client.post("/api/devices", headers=headers, json=body)
    j = res.json()
    return j["id"], j["api_key"]


async def test_ingest_without_api_key_rejected(client: AsyncClient):
    res = await client.post(
        "/api/gps/ingest",
        json={"points": [{"latitude": 0, "longitude": 0}]},
    )
    assert res.status_code == 401


async def test_ingest_with_wrong_key_rejected(client: AsyncClient):
    res = await client.post(
        "/api/gps/ingest",
        headers={"X-API-Key": "bogus", "X-IMEI": "352094081234567"},
        json={"points": [{"latitude": 0, "longitude": 0}]},
    )
    assert res.status_code == 401


async def test_ingest_with_device_key_succeeds(client: AsyncClient, admin_headers):
    truck_id = await _create_truck(client, admin_headers)
    _, api_key = await _enroll_device(client, admin_headers, "352094081234567", truck_id)

    res = await client.post(
        "/api/gps/ingest",
        headers={"X-API-Key": api_key, "X-IMEI": "352094081234567"},
        json={"points": [{"latitude": 41.3, "longitude": 69.2, "speed": 12.5}]},
    )
    assert res.status_code == 200
    assert res.json()["updated"] == 1


async def test_ingest_updates_truck_status_to_moving(
    client: AsyncClient, admin_headers
):
    truck_id = await _create_truck(client, admin_headers)
    _, api_key = await _enroll_device(client, admin_headers, "352094081234567", truck_id)

    await client.post(
        "/api/gps/ingest",
        headers={"X-API-Key": api_key, "X-IMEI": "352094081234567"},
        json={"points": [{"latitude": 41.3, "longitude": 69.2, "speed": 20.0}]},
    )

    listed = await client.get("/api/trucks", headers=admin_headers)
    assert listed.json()[0]["status"] == "moving"


async def test_ingest_status_stopped_for_zero_speed(
    client: AsyncClient, admin_headers
):
    truck_id = await _create_truck(client, admin_headers)
    _, api_key = await _enroll_device(client, admin_headers, "352094081234567", truck_id)

    await client.post(
        "/api/gps/ingest",
        headers={"X-API-Key": api_key, "X-IMEI": "352094081234567"},
        json={"points": [{"latitude": 41.3, "longitude": 69.2, "speed": 0.0}]},
    )

    listed = await client.get("/api/trucks", headers=admin_headers)
    assert listed.json()[0]["status"] == "stopped"


async def test_locations_endpoint_returns_latest(
    client: AsyncClient, admin_headers
):
    truck_id = await _create_truck(client, admin_headers)
    _, api_key = await _enroll_device(client, admin_headers, "352094081234567", truck_id)

    await client.post(
        "/api/gps/ingest",
        headers={"X-API-Key": api_key, "X-IMEI": "352094081234567"},
        json={"points": [{"latitude": 41.3, "longitude": 69.2, "speed": 10.0}]},
    )

    res = await client.get("/api/trucks/locations", headers=admin_headers)
    assert res.status_code == 200
    locations = res.json()
    assert len(locations) == 1
    assert locations[0]["latitude"] == 41.3
    assert locations[0]["longitude"] == 69.2


async def test_ingest_uses_device_truck_binding(
    client: AsyncClient, admin_headers
):
    """Device is bound to a truck at enrollment; ingest doesn't need truck_id."""
    truck_id = await _create_truck(client, admin_headers)
    _, api_key = await _enroll_device(client, admin_headers, "352094081234567", truck_id)

    res = await client.post(
        "/api/gps/ingest",
        headers={"X-API-Key": api_key, "X-IMEI": "352094081234567"},
        json={"points": [{"latitude": 41.3, "longitude": 69.2, "speed": 5.0}]},
    )
    assert res.status_code == 200
    assert res.json()["updated"] == 1


async def test_legacy_fleet_wide_key_is_rejected(
    client: AsyncClient, admin_headers, monkeypatch
):
    """A configured fleet-wide key must not authenticate anything any more.

    It used to, and because such a key belongs to no organization the tenant
    check on ingest had nothing to compare the target truck against and was
    skipped — any holder could write a position onto any customer's truck.
    """
    from app.core.config import settings

    monkeypatch.setattr(settings, "gps_api_keys", "legacy-test-key", raising=False)
    truck_id = await _create_truck(client, admin_headers)

    res = await client.post(
        "/api/gps/ingest",
        headers={"X-API-Key": "legacy-test-key"},
        json={"points": [{"truck_id": truck_id, "latitude": 1.0, "longitude": 2.0, "speed": 8}]},
    )
    assert res.status_code == 401


async def test_ingest_without_imei_is_rejected(client: AsyncClient):
    """No IMEI means no device, and there is no keyed fallback behind it."""
    res = await client.post(
        "/api/gps/ingest",
        headers={"X-API-Key": "anything"},
        json={"points": [{"latitude": 1.0, "longitude": 2.0}]},
    )
    assert res.status_code == 401


# ── Batch handling ────────────────────────────────────────────────────
#
# A tracker that loses signal buffers its fixes and flushes them as one batch.
# That shape used to cost a truck lookup, a full geofence read and a per-fence
# state query *per point*, plus one WebSocket frame per point.


@contextlib.contextmanager
def counting_queries() -> "list[str]":
    """Record every SQL statement the app issues inside the block."""
    seen: list[str] = []

    def record(conn, cursor, statement, parameters, context, executemany):
        seen.append(statement)

    sa.event.listen(engine.sync_engine, "before_cursor_execute", record)
    try:
        yield seen
    finally:
        sa.event.remove(engine.sync_engine, "before_cursor_execute", record)


@contextlib.contextmanager
def capturing_broadcasts() -> "list[dict]":
    """Record every WebSocket message the app fans out inside the block."""
    sent: list[dict] = []
    original = ws_manager.broadcast_to_org

    async def record(org_id, message):
        sent.append(message)
        return await original(org_id, message)

    ws_manager.broadcast_to_org = record
    try:
        yield sent
    finally:
        ws_manager.broadcast_to_org = original


def _point(lat: float, lng: float, when: str, speed: float = 30.0) -> dict:
    return {"latitude": lat, "longitude": lng, "speed": speed, "recorded_at": when}


async def test_batch_stores_every_point_but_broadcasts_one_position(
    client: AsyncClient, admin_headers
):
    """The map draws a position; the history table keeps the track.

    Fifty frames for one flush is forty-nine repaints of already-stale data.
    """
    truck_id = await _create_truck(client, admin_headers)
    _, api_key = await _enroll_device(client, admin_headers, "352094081234567", truck_id)

    points = [
        _point(41.30, 69.20, "2026-09-01T10:00:00+00:00"),
        _point(41.31, 69.21, "2026-09-01T10:00:15+00:00"),
        _point(41.32, 69.22, "2026-09-01T10:00:30+00:00"),
    ]

    with capturing_broadcasts() as sent:
        res = await client.post(
            "/api/gps/ingest",
            headers={"X-API-Key": api_key, "X-IMEI": "352094081234567"},
            json={"points": points},
        )

    assert res.status_code == 200
    assert res.json()["updated"] == 3

    locations = await client.get("/api/trucks/locations", headers=admin_headers)
    assert locations.json()[0]["latitude"] == 41.32  # the newest fix wins

    positions = [m for m in sent if m["type"] == "truck_location_update"]
    assert len(positions) == 1, f"one frame per truck per flush, got {len(positions)}"
    assert positions[0]["lat"] == 41.32


async def test_out_of_order_batch_still_leaves_the_newest_fix_as_latest(
    client: AsyncClient, admin_headers
):
    """A flushed buffer does not promise payload order; recorded_at decides."""
    truck_id = await _create_truck(client, admin_headers)
    _, api_key = await _enroll_device(client, admin_headers, "352094081234567", truck_id)

    res = await client.post(
        "/api/gps/ingest",
        headers={"X-API-Key": api_key, "X-IMEI": "352094081234567"},
        json={
            "points": [
                _point(41.32, 69.22, "2026-09-01T10:00:30+00:00"),
                _point(41.30, 69.20, "2026-09-01T10:00:00+00:00"),
                _point(41.31, 69.21, "2026-09-01T10:00:15+00:00"),
            ]
        },
    )
    assert res.status_code == 200

    locations = await client.get("/api/trucks/locations", headers=admin_headers)
    assert locations.json()[0]["latitude"] == 41.32


async def test_batch_query_count_does_not_grow_with_points(
    client: AsyncClient, admin_headers
):
    """The regression guard for the N+1 this endpoint used to be.

    Ten points must not cost ten times what one point costs. The bound is
    deliberately loose — this asserts the shape of the work, not a fixed plan.
    """
    truck_id = await _create_truck(client, admin_headers)
    _, api_key = await _enroll_device(client, admin_headers, "352094081234567", truck_id)
    await client.post(
        "/api/geofences",
        headers=admin_headers,
        json={
            "name": "Depot",
            "category": "depot",
            "center_lat": 41.30,
            "center_lng": 69.20,
            "radius_m": 500,
        },
    )

    headers = {"X-API-Key": api_key, "X-IMEI": "352094081234567"}
    one = [_point(41.40, 69.30, "2026-09-01T10:00:00+00:00")]
    many = [
        _point(41.40 + i / 1000, 69.30, f"2026-09-01T10:{i:02d}:00+00:00")
        for i in range(10)
    ]

    with counting_queries() as first:
        await client.post("/api/gps/ingest", headers=headers, json={"points": one})
    with counting_queries() as second:
        await client.post("/api/gps/ingest", headers=headers, json={"points": many})

    # Ten history rows go out as one executemany, and everything else in the
    # request — truck lookup, fence read, fence state, latest-location upsert,
    # status update — is settled once per truck whatever the batch size. So the
    # count must be flat, not merely sub-linear.
    assert len(second) <= len(first) + 2, (
        f"ingest cost grows with batch size again: {len(first)} query(s) for "
        f"1 point, {len(second)} for {len(many)}"
    )


async def test_enter_and_exit_inside_one_flush_are_both_recorded(
    client: AsyncClient, admin_headers
):
    """A truck that visited a depot while offline still visited it.

    Each point used to re-read fence state from the database, and events
    created earlier in the same request had not been flushed — so the visit
    either vanished or repeated, depending on the order of the points.
    """
    truck_id = await _create_truck(client, admin_headers)
    _, api_key = await _enroll_device(client, admin_headers, "352094081234567", truck_id)
    fence = await client.post(
        "/api/geofences",
        headers=admin_headers,
        json={
            "name": "Depot",
            "category": "depot",
            "center_lat": 41.30,
            "center_lng": 69.20,
            "radius_m": 500,
        },
    )
    assert fence.status_code in (200, 201), fence.text

    res = await client.post(
        "/api/gps/ingest",
        headers={"X-API-Key": api_key, "X-IMEI": "352094081234567"},
        json={
            "points": [
                _point(41.40, 69.30, "2026-09-01T09:00:00+00:00"),  # outside
                _point(41.30, 69.20, "2026-09-01T09:30:00+00:00"),  # inside → enter
                _point(41.3001, 69.2001, "2026-09-01T10:00:00+00:00"),  # still inside
                _point(41.45, 69.35, "2026-09-01T10:30:00+00:00"),  # outside → exit
            ]
        },
    )
    assert res.status_code == 200

    events = await client.get("/api/geofences/events", headers=admin_headers)
    assert events.status_code == 200, events.text
    kinds = [e["event"] for e in events.json()]
    assert kinds.count("enter") == 1, f"expected one enter, got {kinds}"
    assert kinds.count("exit") == 1, f"expected one exit, got {kinds}"


async def test_device_cannot_write_onto_another_orgs_truck(client: AsyncClient):
    """The tenant check is a WHERE clause now, not a per-point comparison."""
    async def signup(email: str, org: str) -> dict[str, str]:
        await client.post(
            "/api/auth/register",
            json={"email": email, "password": "password123", "org_name": org},
        )
        login = await client.post(
            "/api/auth/login", json={"email": email, "password": "password123"}
        )
        return {"Authorization": f"Bearer {login.json()['access_token']}"}

    a = await signup("gps-a@org.com", "GPS Org A")
    b = await signup("gps-b@org.com", "GPS Org B")

    a_truck = await _create_truck(client, a)
    _, b_key = await _enroll_device(client, b, "352094089999999")

    res = await client.post(
        "/api/gps/ingest",
        headers={"X-API-Key": b_key, "X-IMEI": "352094089999999"},
        json={"points": [{"truck_id": a_truck, "latitude": 1.0, "longitude": 2.0}]},
    )
    assert res.status_code == 200
    assert res.json()["updated"] == 0, "Org B wrote a position onto Org A's truck"

    a_locations = await client.get("/api/trucks/locations", headers=a)
    assert a_locations.json() == []
