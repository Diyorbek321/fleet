"""Truck CRUD + auth gating."""
from __future__ import annotations

from httpx import AsyncClient


async def test_list_trucks_requires_auth(client: AsyncClient):
    res = await client.get("/api/trucks")
    assert res.status_code == 401


async def test_create_and_list_trucks(client: AsyncClient, admin_headers):
    res = await client.post(
        "/api/trucks",
        headers=admin_headers,
        json={"name": "Alpha", "plate_number": "AA-01", "model": "Volvo FH16"},
    )
    assert res.status_code == 200
    created = res.json()
    assert created["name"] == "Alpha"
    assert created["plate_number"] == "AA-01"
    assert created["status"] == "offline"

    listed = await client.get("/api/trucks", headers=admin_headers)
    assert listed.status_code == 200
    trucks = listed.json()
    assert len(trucks) == 1
    assert trucks[0]["id"] == created["id"]


async def test_get_single_truck(client: AsyncClient, admin_headers):
    created = (
        await client.post(
            "/api/trucks",
            headers=admin_headers,
            json={"name": "A", "plate_number": "AA-01"},
        )
    ).json()

    res = await client.get(f"/api/trucks/{created['id']}", headers=admin_headers)
    assert res.status_code == 200
    assert res.json()["id"] == created["id"]
    assert res.json()["location"] is None  # no GPS yet


async def test_get_missing_truck_404(client: AsyncClient, admin_headers):
    res = await client.get(
        "/api/trucks/00000000-0000-0000-0000-000000000000",
        headers=admin_headers,
    )
    assert res.status_code == 404
