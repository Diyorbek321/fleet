"""Multi-tenancy isolation: one organization can never see or touch another's data."""
from __future__ import annotations

import pytest
from httpx import AsyncClient


async def _signup(client: AsyncClient, email: str, org_name: str) -> dict[str, str]:
    await client.post(
        "/api/auth/register",
        json={"email": email, "password": "password123", "org_name": org_name},
    )
    login = await client.post(
        "/api/auth/login", json={"email": email, "password": "password123"}
    )
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.fixture
async def two_orgs(client: AsyncClient):
    a = await _signup(client, "a@org.com", "Org A")
    b = await _signup(client, "b@org.com", "Org B")
    return a, b


async def test_truck_lists_are_isolated(client: AsyncClient, two_orgs):
    a_headers, b_headers = two_orgs

    created = await client.post(
        "/api/trucks", headers=a_headers, json={"name": "A-Truck", "plate_number": "A-001"}
    )
    assert created.status_code == 200, created.text
    a_truck_id = created.json()["id"]

    # Org B's list must not contain Org A's truck.
    b_list = await client.get("/api/trucks", headers=b_headers)
    assert b_list.status_code == 200
    assert all(t["id"] != a_truck_id for t in b_list.json())

    # Org A's own list does contain it.
    a_list = await client.get("/api/trucks", headers=a_headers)
    assert any(t["id"] == a_truck_id for t in a_list.json())


async def test_cross_org_truck_access_is_404(client: AsyncClient, two_orgs):
    a_headers, b_headers = two_orgs
    created = await client.post(
        "/api/trucks", headers=a_headers, json={"name": "A-Truck", "plate_number": "A-002"}
    )
    a_truck_id = created.json()["id"]

    # Org B cannot read, update or delete Org A's truck — all 404 (not 403, to
    # avoid leaking existence).
    assert (await client.get(f"/api/trucks/{a_truck_id}", headers=b_headers)).status_code == 404
    assert (
        await client.put(
            f"/api/trucks/{a_truck_id}", headers=b_headers, json={"name": "hacked"}
        )
    ).status_code == 404
    assert (await client.delete(f"/api/trucks/{a_truck_id}", headers=b_headers)).status_code == 404

    # And Org A still owns an unmodified truck.
    still = await client.get(f"/api/trucks/{a_truck_id}", headers=a_headers)
    assert still.status_code == 200
    assert still.json()["name"] == "A-Truck"


async def test_cross_org_driver_access_is_isolated(client: AsyncClient, two_orgs):
    a_headers, b_headers = two_orgs
    created = await client.post(
        "/api/drivers", headers=a_headers, json={"name": "A Driver", "license_number": "A-LIC-1"}
    )
    assert created.status_code == 200, created.text
    a_driver_id = created.json()["id"]

    assert (await client.get(f"/api/drivers/{a_driver_id}", headers=b_headers)).status_code == 404
    b_list = await client.get("/api/drivers", headers=b_headers)
    assert all(d["id"] != a_driver_id for d in b_list.json())
