"""A trip takes the driver bound to its truck.

The driver is put on a truck once, on the driver's page. Asking again on every
trip was a second place to get it wrong, so the trip form no longer asks.
"""
from __future__ import annotations

from httpx import AsyncClient


async def _truck(client: AsyncClient, headers: dict, plate: str) -> str:
    res = await client.post("/api/trucks", headers=headers, json={"name": plate, "plate_number": plate})
    assert res.status_code in (200, 201), res.text
    return res.json()["id"]


async def _driver(client: AsyncClient, headers: dict, name: str, truck_id: str | None = None) -> str:
    res = await client.post("/api/drivers", headers=headers, json={"name": name, "license_number": f"L-{name}"})
    driver_id = res.json()["id"]
    if truck_id:
        res = await client.post(f"/api/drivers/{driver_id}/assign", headers=headers, json={"truck_id": truck_id})
        assert res.status_code == 200, res.text
    return driver_id


async def test_a_new_trip_takes_the_trucks_driver(client: AsyncClient, admin_headers):
    truck_id = await _truck(client, admin_headers, "01A111AA")
    driver_id = await _driver(client, admin_headers, "Ali", truck_id)

    res = await client.post("/api/trips", headers=admin_headers, json={"truck_id": truck_id})

    assert res.status_code == 200, res.text
    assert res.json()["driver_id"] == driver_id


async def test_a_truck_without_a_driver_leaves_the_trip_unassigned(client: AsyncClient, admin_headers):
    truck_id = await _truck(client, admin_headers, "01A222AA")

    res = await client.post("/api/trips", headers=admin_headers, json={"truck_id": truck_id})

    assert res.json()["driver_id"] is None


async def test_changing_the_truck_brings_its_driver(client: AsyncClient, admin_headers):
    first = await _truck(client, admin_headers, "01A333AA")
    second = await _truck(client, admin_headers, "01A444AA")
    await _driver(client, admin_headers, "Vali", first)
    second_driver = await _driver(client, admin_headers, "Sami", second)
    trip_id = (await client.post("/api/trips", headers=admin_headers, json={"truck_id": first})).json()["id"]

    res = await client.put(f"/api/trips/{trip_id}", headers=admin_headers, json={"truck_id": second})

    assert res.json()["driver_id"] == second_driver


async def test_resaving_a_trip_keeps_its_driver(client: AsyncClient, admin_headers):
    """The truck may have changed hands since; an edit of the notes must not
    hand a running trip to the new driver."""
    truck_id = await _truck(client, admin_headers, "01A555AA")
    first_driver = await _driver(client, admin_headers, "Odil", truck_id)
    trip_id = (await client.post("/api/trips", headers=admin_headers, json={"truck_id": truck_id})).json()["id"]
    await _driver(client, admin_headers, "Botir", truck_id)

    res = await client.put(
        f"/api/trips/{trip_id}", headers=admin_headers, json={"truck_id": truck_id, "notes": "x"}
    )

    assert res.json()["driver_id"] == first_driver
