"""Device enrollment: admin-gated, API keys returned once, rotation, deletion."""
from __future__ import annotations

from httpx import AsyncClient


async def _create_truck(client: AsyncClient, headers: dict) -> str:
    res = await client.post(
        "/api/trucks",
        headers=headers,
        json={"name": "T1", "plate_number": "X-01"},
    )
    return res.json()["id"]


async def test_enroll_requires_admin(client: AsyncClient, operator_headers):
    res = await client.post(
        "/api/devices",
        headers=operator_headers,
        json={"imei": "352094081234567"},
    )
    assert res.status_code == 403


async def test_enroll_returns_api_key_once(client: AsyncClient, admin_headers):
    res = await client.post(
        "/api/devices",
        headers=admin_headers,
        json={"imei": "352094081234567", "name": "Teltonika FMB920"},
    )
    assert res.status_code == 201
    body = res.json()
    assert body["api_key"]  # plaintext returned once
    assert len(body["api_key"]) >= 32  # token_urlsafe(32)
    assert body["imei"] == "352094081234567"
    assert body["name"] == "Teltonika FMB920"

    # Subsequent listing never re-exposes api_key
    listed = await client.get("/api/devices", headers=admin_headers)
    assert listed.status_code == 200
    first = listed.json()[0]
    assert "api_key" not in first
    assert "api_key_hash" not in first


async def test_enroll_duplicate_imei_rejected(client: AsyncClient, admin_headers):
    payload = {"imei": "352094081234567"}
    await client.post("/api/devices", headers=admin_headers, json=payload)
    dup = await client.post("/api/devices", headers=admin_headers, json=payload)
    assert dup.status_code == 409


async def test_rotate_key_invalidates_old(client: AsyncClient, admin_headers):
    enroll = await client.post(
        "/api/devices", headers=admin_headers, json={"imei": "352094081234567"}
    )
    device_id = enroll.json()["id"]
    old_key = enroll.json()["api_key"]

    rotate = await client.post(
        f"/api/devices/{device_id}/rotate-key", headers=admin_headers
    )
    assert rotate.status_code == 200
    new_key = rotate.json()["api_key"]
    assert new_key != old_key

    # Old key no longer works for ingest
    bad = await client.post(
        "/api/gps/ingest",
        headers={"X-API-Key": old_key, "X-IMEI": "352094081234567"},
        json={"points": [{"latitude": 0, "longitude": 0}]},
    )
    assert bad.status_code == 401


async def test_delete_device(client: AsyncClient, admin_headers):
    enroll = await client.post(
        "/api/devices", headers=admin_headers, json={"imei": "352094081234567"}
    )
    device_id = enroll.json()["id"]

    res = await client.delete(f"/api/devices/{device_id}", headers=admin_headers)
    assert res.status_code == 204

    listed = await client.get("/api/devices", headers=admin_headers)
    assert listed.json() == []


async def test_delete_requires_admin(client: AsyncClient, admin_headers, operator_headers):
    enroll = await client.post(
        "/api/devices", headers=admin_headers, json={"imei": "352094081234567"}
    )
    device_id = enroll.json()["id"]

    res = await client.delete(f"/api/devices/{device_id}", headers=operator_headers)
    assert res.status_code == 403


async def test_enroll_with_truck_assignment(client: AsyncClient, admin_headers):
    truck_id = await _create_truck(client, admin_headers)
    res = await client.post(
        "/api/devices",
        headers=admin_headers,
        json={"imei": "352094081234567", "truck_id": truck_id},
    )
    assert res.status_code == 201
    assert res.json()["truck_id"] == truck_id
