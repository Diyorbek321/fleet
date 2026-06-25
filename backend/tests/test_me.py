"""Driver mobile app (`/api/me`) self-scoped endpoints."""
from __future__ import annotations

from httpx import AsyncClient


async def _assign_truck(client: AsyncClient, admin_headers, driver_id: str) -> str:
    truck = (
        await client.post(
            "/api/trucks",
            headers=admin_headers,
            json={"name": "Truck 1", "plate_number": "TR-01"},
        )
    ).json()
    res = await client.post(
        f"/api/drivers/{driver_id}/assign",
        headers=admin_headers,
        json={"truck_id": truck["id"]},
    )
    assert res.status_code in (200, 201), res.text
    return truck["id"]


async def test_me_requires_auth(client: AsyncClient):
    assert (await client.get("/api/me/profile")).status_code == 401


async def test_non_driver_forbidden(client: AsyncClient, admin_headers):
    # An admin account isn't linked to a driver profile.
    res = await client.get("/api/me/profile", headers=admin_headers)
    assert res.status_code == 403


async def test_profile_and_empty_assignment(client: AsyncClient, driver_login):
    h = driver_login["headers"]
    prof = await client.get("/api/me/profile", headers=h)
    assert prof.status_code == 200
    assert prof.json()["name"] == "Bob Driver"

    assign = await client.get("/api/me/assignment", headers=h)
    assert assign.status_code == 200
    assert assign.json() is None  # no truck yet


async def test_assignment_after_assign(client: AsyncClient, admin_headers, driver_login):
    truck_id = await _assign_truck(client, admin_headers, driver_login["driver_id"])
    assign = await client.get("/api/me/assignment", headers=driver_login["headers"])
    assert assign.status_code == 200
    assert assign.json()["id"] == truck_id


async def test_shift_lifecycle(client: AsyncClient, admin_headers, driver_login):
    h = driver_login["headers"]
    await _assign_truck(client, admin_headers, driver_login["driver_id"])

    assert (await client.get("/api/me/shifts/current", headers=h)).json() is None

    start = await client.post("/api/me/shifts/start", headers=h, json={"start_mileage": 1000})
    assert start.status_code == 201, start.text
    assert start.json()["status"] == "active"

    # Cannot start a second active shift.
    assert (await client.post("/api/me/shifts/start", headers=h, json={})).status_code == 409

    end = await client.post("/api/me/shifts/end", headers=h, json={"end_mileage": 1080})
    assert end.status_code == 200
    assert end.json()["status"] == "ended"
    assert (await client.post("/api/me/shifts/end", headers=h, json={})).status_code == 409


async def test_location_ping_requires_truck(client: AsyncClient, admin_headers, driver_login):
    h = driver_login["headers"]
    body = {"latitude": 41.3, "longitude": 69.2, "speed": 30}
    # No truck assigned yet.
    assert (await client.post("/api/me/location", headers=h, json=body)).status_code == 409

    truck_id = await _assign_truck(client, admin_headers, driver_login["driver_id"])
    ping = await client.post("/api/me/location", headers=h, json=body)
    assert ping.status_code == 200
    assert ping.json()["truck_id"] == truck_id

    # The admin live view now sees the truck location.
    loc = await client.get(f"/api/trucks/{truck_id}/location", headers=admin_headers)
    assert loc.status_code == 200
    assert abs(float(loc.json()["latitude"]) - 41.3) < 0.001


async def test_fuel_log_create_and_list(client: AsyncClient, admin_headers, driver_login):
    h = driver_login["headers"]
    await _assign_truck(client, admin_headers, driver_login["driver_id"])

    res = await client.post(
        "/api/me/fuel-logs",
        headers=h,
        json={"liters": 50, "cost_per_liter": 1.2, "mileage_at_fill": 1000},
    )
    assert res.status_code == 201, res.text
    assert abs(res.json()["total_cost"] - 60.0) < 0.001  # auto-computed

    logs = await client.get("/api/me/fuel-logs", headers=h)
    assert logs.status_code == 200
    assert len(logs.json()) == 1


async def test_report_issue(client: AsyncClient, admin_headers, driver_login):
    h = driver_login["headers"]
    await _assign_truck(client, admin_headers, driver_login["driver_id"])
    res = await client.post(
        "/api/me/maintenance-requests",
        headers=h,
        json={"title": "Brake noise", "description": "Squealing on left front"},
    )
    assert res.status_code == 201, res.text
    assert res.json()["status"] == "open"

    listed = await client.get("/api/me/maintenance-requests", headers=h)
    assert len(listed.json()) == 1


async def test_push_token_register(client: AsyncClient, driver_login):
    h = driver_login["headers"]
    res = await client.post(
        "/api/me/push-token",
        headers=h,
        json={"token": "ExponentPushToken[abc123]", "platform": "expo"},
    )
    assert res.status_code == 201
    # Idempotent re-register of the same token.
    assert (
        await client.post(
            "/api/me/push-token",
            headers=h,
            json={"token": "ExponentPushToken[abc123]", "platform": "expo"},
        )
    ).status_code == 201
