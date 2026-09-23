"""Who moved the money figures, and can the owner find out.

Fuel logs are append-only — there is no route that edits or deletes one, so the
litres a leakage report reads cannot be revised after the fact. What *is*
editable is everything around them: a trip can be deleted, taking its rate, its
fuel and its expenses out of every report at once; the USD rate that converts
every cross-border expense report can be moved by one number. Until these rows
existed, none of that left a trace, and the owner had no way to ask who did it.
"""
from __future__ import annotations

from httpx import AsyncClient


async def _fleet(client: AsyncClient, admin_headers) -> tuple[str, str]:
    truck = await client.post(
        "/api/trucks", headers=admin_headers, json={"name": "Audited", "plate_number": "AUD-1"}
    )
    driver = await client.post(
        "/api/drivers", headers=admin_headers, json={"name": "Aziz", "license_number": "AUD-LIC"}
    )
    return truck.json()["id"], driver.json()["id"]


async def _entries(client: AsyncClient, admin_headers, **params) -> list[dict]:
    res = await client.get("/api/audit", headers=admin_headers, params=params)
    assert res.status_code == 200, res.text
    return res.json()


async def test_deleting_a_trip_is_recorded_with_what_it_was_worth(
    client: AsyncClient, admin_headers
):
    truck_id, driver_id = await _fleet(client, admin_headers)
    trip = await client.post(
        "/api/trips",
        headers=admin_headers,
        json={"truck_id": truck_id, "driver_id": driver_id, "rate": 42_000_000},
    )
    trip_id = trip.json()["id"]

    assert (await client.delete(f"/api/trips/{trip_id}", headers=admin_headers)).status_code == 200

    entries = await _entries(client, admin_headers, action="trip.delete")
    assert len(entries) == 1, entries
    entry = entries[0]
    assert entry["target_id"] == trip_id
    assert entry["actor_email"] == "admin@test.com"
    # The rate has to be in the row: the trip it described is gone.
    assert "42000000" in entry["detail"].replace("'", "").replace(" ", "")


async def test_changing_a_rate_records_both_numbers(client: AsyncClient, admin_headers):
    truck_id, driver_id = await _fleet(client, admin_headers)
    trip = await client.post(
        "/api/trips",
        headers=admin_headers,
        json={"truck_id": truck_id, "driver_id": driver_id, "rate": 42_000_000},
    )
    trip_id = trip.json()["id"]

    edited = await client.put(
        f"/api/trips/{trip_id}", headers=admin_headers, json={"rate": 38_000_000}
    )
    assert edited.status_code == 200, edited.text

    entries = await _entries(client, admin_headers, action="trip.update")
    assert len(entries) == 1, entries
    detail = entries[0]["detail"]
    assert "42000000" in detail.replace("'", "").replace(" ", "")
    assert "38000000" in detail.replace("'", "").replace(" ", "")


async def test_an_edit_that_moves_no_watched_figure_writes_nothing(
    client: AsyncClient, admin_headers
):
    """A log that records every save is a log nobody reads."""
    truck_id, driver_id = await _fleet(client, admin_headers)
    trip = await client.post(
        "/api/trips",
        headers=admin_headers,
        json={"truck_id": truck_id, "driver_id": driver_id, "rate": 1_000_000},
    )
    trip_id = trip.json()["id"]

    same = await client.put(
        f"/api/trips/{trip_id}", headers=admin_headers, json={"rate": 1_000_000}
    )
    assert same.status_code == 200

    assert await _entries(client, admin_headers, action="trip.update") == []


async def test_moving_an_exchange_rate_is_recorded(client: AsyncClient, admin_headers):
    """One number here restates every cross-border report the company ever filed."""
    res = await client.put(
        "/api/org/settings",
        headers=admin_headers,
        json={"usd_to_kzt": 500, "usd_to_rub": 95, "usd_to_uzs": 12800},
    )
    assert res.status_code == 200, res.text

    entries = await _entries(client, admin_headers, action="org_settings.update")
    assert len(entries) == 1, entries
    assert "usd_to_uzs" in entries[0]["detail"]


async def test_deleting_a_truck_is_recorded_by_plate(client: AsyncClient, admin_headers):
    truck_id, _ = await _fleet(client, admin_headers)

    assert (await client.delete(f"/api/trucks/{truck_id}", headers=admin_headers)).status_code == 200

    entries = await _entries(client, admin_headers, action="truck.delete")
    assert len(entries) == 1
    assert entries[0]["target_label"] == "AUD-1"


async def test_a_rolled_back_change_leaves_no_entry(client: AsyncClient, admin_headers):
    """The row rides the same transaction as the change it describes.

    A log entry for something that did not happen is worse than none: it sends
    someone looking for a trip that is still there.
    """
    truck_id, driver_id = await _fleet(client, admin_headers)
    trip = await client.post(
        "/api/trips",
        headers=admin_headers,
        json={"truck_id": truck_id, "driver_id": driver_id, "rate": 5_000_000},
    )
    trip_id = trip.json()["id"]

    # A truck id from no organization: the handler 404s after the audit call
    # site would have run for a legitimate edit.
    rejected = await client.put(
        f"/api/trips/{trip_id}",
        headers=admin_headers,
        json={"rate": 1, "truck_id": "00000000-0000-0000-0000-000000000000"},
    )
    assert rejected.status_code == 404

    assert await _entries(client, admin_headers, action="trip.update") == []
    still_there = await client.get(f"/api/trips/{trip_id}", headers=admin_headers)
    assert still_there.json()["rate"] == "5000000.00" or float(still_there.json()["rate"]) == 5_000_000


async def test_the_log_is_admin_only(client: AsyncClient, operator_headers):
    """The people who can delete a trip do not decide what the log says."""
    res = await client.get("/api/audit", headers=operator_headers)
    assert res.status_code == 403, res.text


async def test_one_fleets_log_never_shows_anothers(client: AsyncClient):
    """A leak here would name the records a competitor had deleted."""
    async def signup(email: str, org: str) -> dict[str, str]:
        await client.post(
            "/api/auth/register",
            json={"email": email, "password": "password123", "org_name": org},
        )
        login = await client.post(
            "/api/auth/login", json={"email": email, "password": "password123"}
        )
        return {"Authorization": f"Bearer {login.json()['access_token']}"}

    a = await signup("audit-a@org.com", "Audit Org A")
    b = await signup("audit-b@org.com", "Audit Org B")

    truck = await client.post(
        "/api/trucks", headers=a, json={"name": "A", "plate_number": "AUD-A1"}
    )
    await client.delete(f"/api/trucks/{truck.json()['id']}", headers=a)

    assert len(await _entries(client, a, action="truck.delete")) == 1
    assert await _entries(client, b, action="truck.delete") == []
