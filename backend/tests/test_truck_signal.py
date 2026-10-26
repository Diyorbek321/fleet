"""Which trucks the dispatcher cannot see, and why.

The live map draws a truck only once it has a position, so a truck whose
driver never turned sharing on simply was not there — nothing said it was
missing. This endpoint lists every enabled truck with the one reason it is
not reporting, so the map can show the gap instead of hiding it.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient

from app.services.truck_signal import SignalState, classify

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)
STALE = timedelta(minutes=30)


@pytest.mark.parametrize(
    "has_driver,last_fix_ago,gps_off,expected",
    [
        (True, timedelta(minutes=5), False, SignalState.ok),
        (True, timedelta(minutes=45), False, SignalState.silent),
        (True, None, False, SignalState.never),
        # The phone said so itself: a more useful reason than "silent".
        (True, timedelta(minutes=45), True, SignalState.gps_off),
        # A phone with no truck is refused by the server, whatever it sends.
        (False, timedelta(minutes=5), False, SignalState.no_driver),
        (False, None, False, SignalState.no_driver),
    ],
)
def test_classify(has_driver, last_fix_ago, gps_off, expected):
    state = classify(
        has_driver=has_driver,
        last_fix_at=NOW - last_fix_ago if last_fix_ago else None,
        gps_disabled_at=NOW - timedelta(minutes=50) if gps_off else None,
        now=NOW,
        stale_after=STALE,
    )
    assert state is expected


async def _truck(client: AsyncClient, headers, plate: str) -> str:
    res = await client.post(
        "/api/trucks", headers=headers, json={"name": plate, "plate_number": plate}
    )
    assert res.status_code == 200, res.text
    return res.json()["id"]


async def test_signal_requires_auth(client: AsyncClient):
    assert (await client.get("/api/trucks/signal")).status_code == 401


async def test_signal_lists_every_truck_with_its_reason(
    client: AsyncClient, admin_headers, driver_login
):
    spare = await _truck(client, admin_headers, "SPARE-01")
    assigned = await _truck(client, admin_headers, "LIVE-01")
    res = await client.post(
        f"/api/drivers/{driver_login['driver_id']}/assign",
        headers=admin_headers,
        json={"truck_id": assigned},
    )
    assert res.status_code in (200, 201), res.text

    rows = {r["truck_id"]: r for r in (await client.get("/api/trucks/signal", headers=admin_headers)).json()}
    assert rows[spare]["state"] == "no_driver"
    assert rows[assigned]["state"] == "never"
    assert rows[assigned]["driver_name"] == "Bob Driver"
    assert rows[assigned]["last_fix_at"] is None

    await client.post(
        "/api/me/location",
        headers=driver_login["headers"],
        json={"latitude": 41.3, "longitude": 69.2},
    )
    rows = {r["truck_id"]: r for r in (await client.get("/api/trucks/signal", headers=admin_headers)).json()}
    assert rows[assigned]["state"] == "ok"
    assert rows[assigned]["last_fix_at"] is not None


async def test_disabled_trucks_are_not_listed(client: AsyncClient, admin_headers):
    truck = await _truck(client, admin_headers, "OFF-01")
    await client.put(f"/api/trucks/{truck}", headers=admin_headers, json={"is_enabled": False})
    rows = (await client.get("/api/trucks/signal", headers=admin_headers)).json()
    assert truck not in {r["truck_id"] for r in rows}


async def test_another_fleets_trucks_are_not_listed(client: AsyncClient, admin_headers):
    mine = await _truck(client, admin_headers, "MINE-01")
    await client.post(
        "/api/auth/register",
        json={"email": "other@sig.com", "password": "password123", "org_name": "Other Sig"},
    )
    login = await client.post(
        "/api/auth/login", json={"email": "other@sig.com", "password": "password123"}
    )
    other = {"Authorization": f"Bearer {login.json()['access_token']}"}
    rows = (await client.get("/api/trucks/signal", headers=other)).json()
    assert mine not in {r["truck_id"] for r in rows}
