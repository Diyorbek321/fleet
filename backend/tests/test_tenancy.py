"""Multi-tenancy isolation: one organization can never see or touch another's data.

This is the assertion the business rests on. `get_org_id` is applied by hand in
68 places across the routers, and a single one left off leaks a customer's
fleet, freight rates and driver records to whoever asks — a bug that returns a
200 and looks perfectly healthy in the logs.

So the coverage here is deliberately mechanical rather than interesting: every
tenant-scoped resource, every verb that takes an id, checked the same way. New
resources belong in RESOURCES below, not in a bespoke test.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

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


@dataclass(frozen=True)
class Resource:
    """One tenant-scoped collection, described well enough to probe generically."""

    name: str
    collection: str
    payload: Callable[[str], dict[str, Any]]
    # Some collections answer 200 on create, others 201; both are fine here.
    created_ok: tuple[int, ...] = (200, 201)
    # Verbs that take an id and must not reach across tenants. GET is separate
    # because a few collections have no detail route.
    has_detail_get: bool = True
    update_verb: str | None = "put"
    update_payload: dict[str, Any] = field(default_factory=dict)
    deletable: bool = True

    def detail(self, resource_id: str) -> str:
        return f"{self.collection}/{resource_id}"


RESOURCES: list[Resource] = [
    Resource(
        name="trucks",
        collection="/api/trucks",
        payload=lambda tag: {"name": f"{tag}-Truck", "plate_number": f"{tag}-001"},
        update_payload={"name": "hijacked"},
    ),
    Resource(
        name="drivers",
        collection="/api/drivers",
        payload=lambda tag: {"name": f"{tag} Driver", "license_number": f"{tag}-LIC"},
        update_payload={"name": "hijacked"},
    ),
    Resource(
        name="trips",
        collection="/api/trips",
        payload=lambda tag: {"rate": 5_000_000},
        update_payload={"rate": 1},
    ),
    Resource(
        name="geofences",
        collection="/api/geofences",
        payload=lambda tag: {
            "name": f"{tag} depot",
            "category": "depot",
            "center_lat": 41.30,
            "center_lng": 69.20,
            "radius_m": 500,
        },
        update_payload={"name": "hijacked"},
        has_detail_get=False,
    ),
    Resource(
        name="devices",
        collection="/api/devices",
        # IMEIs are globally unique, so the two orgs must not collide on one.
        payload=lambda tag: {"imei": f"35209408123{'4567' if tag == 'A' else '8901'}"},
        update_payload={"label": "hijacked"},
        has_detail_get=False,
    ),
]

IDS = [r.name for r in RESOURCES]


async def _create(client: AsyncClient, headers, resource: Resource, tag: str) -> str:
    res = await client.post(resource.collection, headers=headers, json=resource.payload(tag))
    assert res.status_code in resource.created_ok, f"{resource.name}: {res.status_code} {res.text}"
    return res.json()["id"]


@pytest.mark.parametrize("resource", RESOURCES, ids=IDS)
class TestIsolation:
    async def test_list_does_not_leak(self, client: AsyncClient, two_orgs, resource: Resource):
        a_headers, b_headers = two_orgs
        a_id = await _create(client, a_headers, resource, "A")

        b_list = await client.get(resource.collection, headers=b_headers)
        assert b_list.status_code == 200, b_list.text
        assert all(row["id"] != a_id for row in b_list.json()), (
            f"{resource.name}: Org B can see Org A's record in the list"
        )

        a_list = await client.get(resource.collection, headers=a_headers)
        assert any(row["id"] == a_id for row in a_list.json())

    async def test_detail_read_is_404(self, client: AsyncClient, two_orgs, resource: Resource):
        if not resource.has_detail_get:
            pytest.skip(f"{resource.name} has no detail GET route")
        a_headers, b_headers = two_orgs
        a_id = await _create(client, a_headers, resource, "A")

        # 404, never 403: a 403 confirms the id exists somewhere on the
        # platform, which is itself a leak between competitors.
        res = await client.get(resource.detail(a_id), headers=b_headers)
        assert res.status_code == 404, f"{resource.name}: {res.status_code}"

    async def test_update_is_404_and_changes_nothing(
        self, client: AsyncClient, two_orgs, resource: Resource
    ):
        if resource.update_verb is None:
            pytest.skip(f"{resource.name} has no update route")
        a_headers, b_headers = two_orgs
        a_id = await _create(client, a_headers, resource, "A")

        res = await client.request(
            resource.update_verb.upper(),
            resource.detail(a_id),
            headers=b_headers,
            json=resource.update_payload,
        )
        assert res.status_code == 404, f"{resource.name}: {res.status_code} {res.text}"

        if resource.has_detail_get:
            still = await client.get(resource.detail(a_id), headers=a_headers)
            assert still.status_code == 200
            for key, hijacked in resource.update_payload.items():
                assert still.json().get(key) != hijacked, (
                    f"{resource.name}: Org B's write landed on Org A's record"
                )

    async def test_delete_is_404_and_record_survives(
        self, client: AsyncClient, two_orgs, resource: Resource
    ):
        if not resource.deletable:
            pytest.skip(f"{resource.name} has no delete route")
        a_headers, b_headers = two_orgs
        a_id = await _create(client, a_headers, resource, "A")

        res = await client.delete(resource.detail(a_id), headers=b_headers)
        assert res.status_code == 404, f"{resource.name}: {res.status_code}"

        a_list = await client.get(resource.collection, headers=a_headers)
        assert any(row["id"] == a_id for row in a_list.json()), (
            f"{resource.name}: Org B deleted Org A's record"
        )


class TestCrossResourceReferences:
    """Ids travel in request bodies too, not just in paths.

    A router that scopes its own collection correctly can still accept a
    foreign id in a field and quietly stitch two tenants together.
    """

    async def test_a_trip_cannot_reference_another_orgs_truck(
        self, client: AsyncClient, two_orgs
    ):
        a_headers, b_headers = two_orgs
        a_truck = await _create(client, a_headers, RESOURCES[0], "A")

        res = await client.post(
            "/api/trips", headers=b_headers, json={"truck_id": a_truck, "rate": 1}
        )
        assert res.status_code in (400, 404, 422), (
            f"Org B attached Org A's truck to its trip: {res.status_code} {res.text}"
        )

    async def test_a_truck_cannot_be_assigned_another_orgs_driver(
        self, client: AsyncClient, two_orgs
    ):
        a_headers, b_headers = two_orgs
        a_driver = await _create(client, a_headers, RESOURCES[1], "A")
        b_truck = await _create(client, b_headers, RESOURCES[0], "B")

        res = await client.post(
            f"/api/drivers/{a_driver}/assign", headers=b_headers, json={"truck_id": b_truck}
        )
        assert res.status_code == 404, f"{res.status_code} {res.text}"

    async def test_fuel_cannot_be_logged_against_another_orgs_truck(
        self, client: AsyncClient, two_orgs
    ):
        """Fuel is money. A write here moves cost onto a competitor's books."""
        a_headers, b_headers = two_orgs
        a_truck = await _create(client, a_headers, RESOURCES[0], "A")

        res = await client.post(
            f"/api/trucks/{a_truck}/fuel-logs",
            headers=b_headers,
            json={"liters": 100, "cost_per_liter": 13000, "odometer": 1000},
        )
        assert res.status_code == 404, f"{res.status_code} {res.text}"

    async def test_maintenance_cannot_be_logged_against_another_orgs_truck(
        self, client: AsyncClient, two_orgs
    ):
        a_headers, b_headers = two_orgs
        a_truck = await _create(client, a_headers, RESOURCES[0], "A")

        res = await client.post(
            f"/api/trucks/{a_truck}/maintenance",
            headers=b_headers,
            json={
                "service_type": "oil_change",
                "cost": 500_000,
                "performed_at": "2026-08-01",
            },
        )
        assert res.status_code == 404, f"{res.status_code} {res.text}"


class TestAnalyticsAreScoped:
    """Read-only endpoints leak just as effectively as writable ones.

    These aggregate across a tenant, so a missing filter does not 404 anywhere
    — it silently blends a competitor's fleet into the numbers.
    """

    async def test_leakage_summary_counts_only_your_own_trucks(
        self, client: AsyncClient, two_orgs
    ):
        a_headers, b_headers = two_orgs
        await _create(client, a_headers, RESOURCES[0], "A")

        res = await client.get("/api/analytics/leakage-summary?days=30", headers=b_headers)
        assert res.status_code == 200, res.text
        body = res.json()
        assert body.get("trucks_flagged", 0) == 0
        assert not body.get("trucks", [])

    async def test_fleet_summary_counts_only_your_own_fleet(
        self, client: AsyncClient, two_orgs
    ):
        a_headers, b_headers = two_orgs
        await _create(client, a_headers, RESOURCES[0], "A")
        await _create(client, a_headers, RESOURCES[1], "A")

        res = await client.get("/api/reports/fleet-summary", headers=b_headers)
        assert res.status_code == 200, res.text
        body = res.json()
        for key in ("total_trucks", "total_drivers"):
            if key in body:
                assert body[key] == 0, f"{key} includes another organization's records"

    async def test_truck_distances_exclude_other_orgs(self, client: AsyncClient, two_orgs):
        a_headers, b_headers = two_orgs
        a_truck = await _create(client, a_headers, RESOURCES[0], "A")

        res = await client.get("/api/reports/truck-distances", headers=b_headers)
        assert res.status_code == 200, res.text
        rows = res.json()
        rows = rows if isinstance(rows, list) else rows.get("trucks", [])
        assert all(row.get("truck_id") != a_truck for row in rows)
