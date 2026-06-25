"""GPS ingest: device auth, legacy key fallback, truck status derivation."""
from __future__ import annotations

from httpx import AsyncClient


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


async def test_ingest_with_legacy_key_still_works(client: AsyncClient, admin_headers):
    """Global GPS_API_KEYS fallback — backwards compat with pre-device-enrollment."""
    truck_id = await _create_truck(client, admin_headers)

    res = await client.post(
        "/api/gps/ingest",
        headers={"X-API-Key": "legacy-test-key"},
        json={"points": [{"truck_id": truck_id, "latitude": 1.0, "longitude": 2.0, "speed": 8}]},
    )
    assert res.status_code == 200
    assert res.json()["updated"] == 1
