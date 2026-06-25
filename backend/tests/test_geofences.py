"""Geofence CRUD + enter/exit detection on GPS ingest."""
from __future__ import annotations

from httpx import AsyncClient


async def _create_truck(client: AsyncClient, headers: dict) -> str:
    res = await client.post(
        "/api/trucks", headers=headers, json={"name": "Alpha", "plate_number": "AA-01"}
    )
    return res.json()["id"]


async def _enroll_device(
    client: AsyncClient, headers: dict, imei: str, truck_id: str
) -> str:
    res = await client.post(
        "/api/devices", headers=headers, json={"imei": imei, "truck_id": truck_id}
    )
    return res.json()["api_key"]


# Depot centered in Tashkent, 500 m radius.
DEPOT = {"name": "Main depot", "category": "depot",
         "center_lat": 41.3000, "center_lng": 69.2000, "radius_m": 500}
INSIDE = {"latitude": 41.3001, "longitude": 69.2001, "speed": 0.0}   # ~14 m from center
OUTSIDE = {"latitude": 41.4000, "longitude": 69.3000, "speed": 30.0}  # ~13 km away


async def _ingest(client: AsyncClient, api_key: str, imei: str, point: dict):
    return await client.post(
        "/api/gps/ingest",
        headers={"X-API-Key": api_key, "X-IMEI": imei},
        json={"points": [point]},
    )


async def test_create_and_list_geofence(client: AsyncClient, admin_headers):
    res = await client.post("/api/geofences", headers=admin_headers, json=DEPOT)
    assert res.status_code == 201, res.text
    assert res.json()["name"] == "Main depot"

    listed = await client.get("/api/geofences", headers=admin_headers)
    assert listed.status_code == 200
    assert len(listed.json()) == 1


async def test_geofence_requires_auth(client: AsyncClient):
    res = await client.get("/api/geofences")
    assert res.status_code == 401


async def test_create_validates_radius(client: AsyncClient, admin_headers):
    bad = {**DEPOT, "radius_m": 0}
    res = await client.post("/api/geofences", headers=admin_headers, json=bad)
    assert res.status_code == 422


async def test_update_and_delete_geofence(client: AsyncClient, admin_headers):
    created = (await client.post("/api/geofences", headers=admin_headers, json=DEPOT)).json()
    gid = created["id"]

    upd = await client.put(
        f"/api/geofences/{gid}", headers=admin_headers, json={"active": False, "name": "Renamed"}
    )
    assert upd.status_code == 200
    assert upd.json()["active"] is False
    assert upd.json()["name"] == "Renamed"

    deleted = await client.delete(f"/api/geofences/{gid}", headers=admin_headers)
    assert deleted.status_code == 204
    assert (await client.get("/api/geofences", headers=admin_headers)).json() == []


async def test_enter_then_exit_emits_two_events(client: AsyncClient, admin_headers):
    truck_id = await _create_truck(client, admin_headers)
    imei = "352094081234567"
    api_key = await _enroll_device(client, admin_headers, imei, truck_id)
    await client.post("/api/geofences", headers=admin_headers, json=DEPOT)

    # enter
    await _ingest(client, api_key, imei, INSIDE)
    # exit
    await _ingest(client, api_key, imei, OUTSIDE)

    events = (await client.get("/api/geofences/events", headers=admin_headers)).json()
    assert len(events) == 2
    kinds = {e["event"] for e in events}
    assert kinds == {"enter", "exit"}


async def test_staying_inside_does_not_duplicate_enter(client: AsyncClient, admin_headers):
    truck_id = await _create_truck(client, admin_headers)
    imei = "352094081234567"
    api_key = await _enroll_device(client, admin_headers, imei, truck_id)
    await client.post("/api/geofences", headers=admin_headers, json=DEPOT)

    # three pings all inside the depot
    for _ in range(3):
        await _ingest(client, api_key, imei, INSIDE)

    events = (await client.get("/api/geofences/events", headers=admin_headers)).json()
    assert len(events) == 1
    assert events[0]["event"] == "enter"


async def test_inactive_geofence_is_ignored(client: AsyncClient, admin_headers):
    truck_id = await _create_truck(client, admin_headers)
    imei = "352094081234567"
    api_key = await _enroll_device(client, admin_headers, imei, truck_id)
    created = (await client.post(
        "/api/geofences", headers=admin_headers, json={**DEPOT, "active": False}
    )).json()

    await _ingest(client, api_key, imei, INSIDE)

    events = (await client.get(
        "/api/geofences/events", headers=admin_headers,
        params={"geofence_id": created["id"]},
    )).json()
    assert events == []
