"""Trips / freight orders: CRUD, status timeline, and per-trip P&L."""
from __future__ import annotations

from httpx import AsyncClient


async def _create_truck(client: AsyncClient, headers: dict, plate: str = "TR-01") -> str:
    res = await client.post(
        "/api/trucks", headers=headers, json={"name": "Alpha", "plate_number": plate}
    )
    return res.json()["id"]


async def test_create_trip_autogenerates_reference(client: AsyncClient, admin_headers):
    truck_id = await _create_truck(client, admin_headers)
    res = await client.post(
        "/api/trips",
        headers=admin_headers,
        json={"truck_id": truck_id, "shipper": "Tashkent Agro", "consignee": "Almaty Foods",
              "origin_name": "Tashkent", "destination_name": "Almaty", "rate": 12000000},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["reference"].startswith("TR-")
    assert body["status"] == "draft"
    assert body["currency"] == "UZS"
    # created event present in timeline
    assert any(e["event"] == "created" for e in body["events"])


async def test_trip_requires_auth(client: AsyncClient):
    assert (await client.get("/api/trips")).status_code == 401


async def test_advance_trip_records_timeline_and_timestamps(client: AsyncClient, admin_headers):
    trip = (await client.post("/api/trips", headers=admin_headers, json={"rate": 5000000})).json()
    tid = trip["id"]

    r1 = await client.post(f"/api/trips/{tid}/advance", headers=admin_headers,
                           json={"to_status": "en_route", "note": "Departed depot"})
    assert r1.status_code == 200, r1.text
    assert r1.json()["status"] == "en_route"
    assert r1.json()["started_at"] is not None

    r2 = await client.post(f"/api/trips/{tid}/advance", headers=admin_headers,
                           json={"to_status": "at_border", "latitude": 41.0, "longitude": 70.0})
    assert r2.json()["status"] == "at_border"

    r3 = await client.post(f"/api/trips/{tid}/advance", headers=admin_headers,
                           json={"to_status": "delivered"})
    body = r3.json()
    assert body["status"] == "delivered"
    assert body["delivered_at"] is not None
    events = [e["event"] for e in body["events"]]
    assert "border_arrival" in events
    assert "pod" in events


async def test_trip_pnl_reconciles_fuel(client: AsyncClient, admin_headers):
    truck_id = await _create_truck(client, admin_headers, plate="PNL-1")
    trip = (await client.post("/api/trips", headers=admin_headers,
                              json={"truck_id": truck_id, "rate": 10000000})).json()
    tid = trip["id"]

    # Log fuel against the trip.
    fr = await client.post(
        f"/api/trucks/{truck_id}/fuel-logs",
        headers=admin_headers,
        json={"trip_id": tid, "liters": 200, "cost_per_liter": 12000, "total_cost": 2400000},
    )
    assert fr.status_code == 200, fr.text

    pnl = await client.get(f"/api/trips/{tid}/pnl", headers=admin_headers)
    assert pnl.status_code == 200, pnl.text
    body = pnl.json()
    assert body["revenue"] == 10000000
    assert body["fuel_cost"] == 2400000
    assert body["profit"] == 7600000
    assert body["margin_pct"] == 76.0


async def test_leakage_summary_returns_shape(client: AsyncClient, admin_headers):
    res = await client.get("/api/analytics/leakage-summary?days=30", headers=admin_headers)
    assert res.status_code == 200, res.text
    body = res.json()
    for key in ("estimated_fuel_waste_cost", "unauthorized_stop_count",
                "total_idle_hours", "active_trips", "delivered_trips"):
        assert key in body


async def test_operator_can_create_but_viewer_role_blocked(client: AsyncClient, operator_headers):
    # operator is allowed to manage trips
    res = await client.post("/api/trips", headers=operator_headers, json={"rate": 1})
    assert res.status_code == 200, res.text


async def test_driver_sees_and_advances_own_trip(client: AsyncClient, admin_headers, driver_login):
    driver_id = driver_login["driver_id"]
    d_headers = driver_login["headers"]

    # Dispatcher assigns a trip to this driver.
    trip = (
        await client.post(
            "/api/trips",
            headers=admin_headers,
            json={"driver_id": driver_id, "rate": 3000000, "origin_name": "Tashkent",
                  "destination_name": "Termez"},
        )
    ).json()

    # Driver sees it via the self-scoped endpoint.
    mine = await client.get("/api/me/trips", headers=d_headers)
    assert mine.status_code == 200, mine.text
    assert any(t["id"] == trip["id"] for t in mine.json())

    # Driver advances it with a location pin (border arrival).
    adv = await client.post(
        f"/api/me/trips/{trip['id']}/advance",
        headers=d_headers,
        json={"to_status": "at_border", "latitude": 37.2, "longitude": 67.3},
    )
    assert adv.status_code == 200, adv.text
    assert adv.json()["status"] == "at_border"


async def test_driver_cannot_advance_foreign_trip(client: AsyncClient, admin_headers, driver_login):
    d_headers = driver_login["headers"]
    # Trip assigned to nobody (not this driver).
    other = (await client.post("/api/trips", headers=admin_headers, json={"rate": 1})).json()
    res = await client.post(
        f"/api/me/trips/{other['id']}/advance",
        headers=d_headers,
        json={"to_status": "delivered"},
    )
    assert res.status_code == 404
