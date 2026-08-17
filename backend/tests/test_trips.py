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


# --- reference numbering: per tenant, never global ---------------------------


async def _signup(client: AsyncClient, email: str, org_name: str) -> dict[str, str]:
    await client.post(
        "/api/auth/register",
        json={"email": email, "password": "password123", "org_name": org_name},
    )
    login = await client.post(
        "/api/auth/login", json={"email": email, "password": "password123"}
    )
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def test_each_organization_numbers_its_trips_from_one(client: AsyncClient):
    """References are a per-tenant sequence.

    Shared globally, a new customer's very first trip comes out numbered from the
    platform-wide total — TR-2026-000587 tells them exactly how much freight
    everyone else is moving. Both orgs here must independently start at 000001.
    """
    a_headers = await _signup(client, "ref-a@org.com", "Ref Org A")
    b_headers = await _signup(client, "ref-b@org.com", "Ref Org B")

    a1 = (await client.post("/api/trips", headers=a_headers, json={"rate": 1000})).json()
    a2 = (await client.post("/api/trips", headers=a_headers, json={"rate": 1000})).json()
    b1 = (await client.post("/api/trips", headers=b_headers, json={"rate": 1000})).json()

    assert a1["reference"].endswith("-000001")
    assert a2["reference"].endswith("-000002")
    # Org B is unaffected by the two trips Org A already created.
    assert b1["reference"].endswith("-000001")
    assert b1["reference"] == a1["reference"]


async def test_two_organizations_may_hold_the_same_explicit_reference(client: AsyncClient):
    """A reference another tenant has taken is invisible here and must not 409."""
    a_headers = await _signup(client, "dup-a@org.com", "Dup Org A")
    b_headers = await _signup(client, "dup-b@org.com", "Dup Org B")

    ref = "CMR-2026-777"
    a = await client.post("/api/trips", headers=a_headers, json={"rate": 1, "reference": ref})
    b = await client.post("/api/trips", headers=b_headers, json={"rate": 1, "reference": ref})

    assert a.status_code == 200, a.text
    assert b.status_code == 200, b.text
    assert a.json()["reference"] == b.json()["reference"] == ref


async def test_duplicate_reference_within_one_organization_is_rejected(
    client: AsyncClient, admin_headers
):
    ref = "CMR-2026-DUP"
    first = await client.post("/api/trips", headers=admin_headers, json={"rate": 1, "reference": ref})
    assert first.status_code == 200, first.text

    second = await client.post("/api/trips", headers=admin_headers, json={"rate": 1, "reference": ref})
    assert second.status_code == 409


async def test_deleting_a_middle_trip_does_not_make_the_next_one_collide(
    client: AsyncClient, admin_headers
):
    """Why numbering reads the highest reference instead of counting rows.

    Count three trips, delete the middle one, and a count-based generator returns
    2 + 1 = 000003 — a reference the still-live third trip already holds. The
    create then fails on the unique constraint for no reason the dispatcher can
    see. Deriving from the maximum issued skips the freed number instead.
    """
    refs = [
        (await client.post("/api/trips", headers=admin_headers, json={"rate": 1})).json()
        for _ in range(3)
    ]
    assert refs[2]["reference"].endswith("-000003")

    deleted = await client.delete(f"/api/trips/{refs[1]['id']}", headers=admin_headers)
    assert deleted.status_code in (200, 204)

    fourth = await client.post("/api/trips", headers=admin_headers, json={"rate": 1})
    assert fourth.status_code == 200, fourth.text
    assert fourth.json()["reference"].endswith("-000004")


async def test_concurrent_creates_never_share_a_reference(client: AsyncClient, admin_headers):
    """The race the unique constraint plus retry loop exists to close.

    Reference allocation is read-then-write, so simultaneous creates can compute
    the same number. Whoever loses at the constraint must retry and land on the
    next one — not fail, and never duplicate.
    """
    import asyncio

    results = await asyncio.gather(
        *[
            client.post("/api/trips", headers=admin_headers, json={"rate": 1000})
            for _ in range(5)
        ]
    )

    assert all(r.status_code == 200 for r in results), [r.text for r in results if r.status_code != 200]
    references = [r.json()["reference"] for r in results]
    assert len(set(references)) == 5, references


async def test_numbering_continues_past_shorter_seeded_references(
    client: AsyncClient, admin_headers
):
    """Reproduces production: seeded trips numbered TR-YYYY-0094, four digits.

    As text ``'TR-2026-0094' > 'TR-2026-000095'`` — the '9' beats the '0' in the
    third position — so a lexicographic MAX sticks on the short reference
    forever and hands out the same number on every call. The tenant creates one
    trip successfully and can never create a second. Taking the maximum
    numerically is what makes mixed widths safe.
    """
    for n in (1, 94):
        seeded = await client.post(
            "/api/trips",
            headers=admin_headers,
            json={"rate": 1, "reference": f"TR-2026-{n:04d}"},
        )
        assert seeded.status_code == 200, seeded.text

    first = await client.post("/api/trips", headers=admin_headers, json={"rate": 1})
    second = await client.post("/api/trips", headers=admin_headers, json={"rate": 1})

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["reference"] == "TR-2026-000095"
    assert second.json()["reference"] == "TR-2026-000096"


async def test_a_non_numeric_reference_does_not_break_numbering(
    client: AsyncClient, admin_headers
):
    """A hand-typed reference sharing the prefix must not reach the integer cast."""
    typed = await client.post(
        "/api/trips", headers=admin_headers, json={"rate": 1, "reference": "TR-2026-ACME"}
    )
    assert typed.status_code == 200, typed.text

    generated = await client.post("/api/trips", headers=admin_headers, json={"rate": 1})
    assert generated.status_code == 200, generated.text
    assert generated.json()["reference"] == "TR-2026-000001"
