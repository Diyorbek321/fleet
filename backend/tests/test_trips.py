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
    # Named after the company, not after an opaque prefix: the reference is read
    # out on the phone and printed on the CMR, where "TR-2026-0012" told nobody
    # whose lorry it was.
    assert body["reference"] == "Test Org-0001"
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
    """References are a per-tenant sequence, under each tenant's own name.

    Shared globally, a new customer's very first trip comes out numbered from the
    platform-wide total — 000587 tells them exactly how much freight everyone
    else is moving. Both orgs here must independently start at 0001, and neither
    may be handed the other's name.
    """
    a_headers = await _signup(client, "ref-a@org.com", "Ref Org A")
    b_headers = await _signup(client, "ref-b@org.com", "Ref Org B")

    a1 = (await client.post("/api/trips", headers=a_headers, json={"rate": 1000})).json()
    a2 = (await client.post("/api/trips", headers=a_headers, json={"rate": 1000})).json()
    b1 = (await client.post("/api/trips", headers=b_headers, json={"rate": 1000})).json()

    assert a1["reference"] == "Ref Org A-0001"
    assert a2["reference"] == "Ref Org A-0002"
    # Org B is unaffected by the two trips Org A already created.
    assert b1["reference"] == "Ref Org B-0001"


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
    assert refs[2]["reference"].endswith("-0003")

    deleted = await client.delete(f"/api/trips/{refs[1]['id']}", headers=admin_headers)
    assert deleted.status_code in (200, 204)

    fourth = await client.post("/api/trips", headers=admin_headers, json={"rate": 1})
    assert fourth.status_code == 200, fourth.text
    assert fourth.json()["reference"].endswith("-0004")


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

    Two things at once. As text ``'TR-2026-0094' > 'TR-2026-000095'`` — the '9'
    beats the '0' in the third position — so a lexicographic MAX sticks on the
    short reference forever and hands out the same number on every call; the
    tenant creates one trip and can never create a second. And a tenant whose
    references were minted under the old ``TR-YYYY-`` scheme must carry on from
    where they were, not open a second sequence at 0001 beside trips they can
    still see. Taking the maximum numerically, across both schemes, is what
    makes the switchover safe.
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
    assert first.json()["reference"] == "Test Org-0095"
    assert second.json()["reference"] == "Test Org-0096"


async def test_a_non_numeric_reference_does_not_break_numbering(
    client: AsyncClient, admin_headers
):
    """A hand-typed reference sharing the prefix must not reach the integer cast."""
    for ref in ("TR-2026-ACME", "Test Org-ACME"):
        typed = await client.post(
            "/api/trips", headers=admin_headers, json={"rate": 1, "reference": ref}
        )
        assert typed.status_code == 200, typed.text

    generated = await client.post("/api/trips", headers=admin_headers, json={"rate": 1})
    assert generated.status_code == 200, generated.text
    assert generated.json()["reference"] == "Test Org-0001"


# ── The company's name at the head of its references ─────────────────────


def test_the_prefix_keeps_the_name_the_customer_writes():
    """"Angren Tek" is how it reads on a CMR, so internal spacing survives."""
    from app.services.trips import reference_prefix

    assert reference_prefix("Angren Tek") == "Angren Tek"
    assert reference_prefix("  Angren   Tek  ") == "Angren Tek"


def test_the_prefix_drops_what_would_break_a_url_or_a_filename():
    """A reference ends up in both."""
    from app.services.trips import reference_prefix

    assert "/" not in reference_prefix("Angren/Tek")
    assert "%" not in reference_prefix("Angren %Tek")
    assert reference_prefix("ООО «Ангрен Тэк»") == "ООО Ангрен Тэк"


def test_an_unnamed_organization_still_gets_a_prefix():
    """A bare number is not a reference anyone can read out."""
    from app.services.trips import reference_prefix

    assert reference_prefix("") == "TR"
    assert reference_prefix(None) == "TR"
    assert reference_prefix("---") == "TR"


def test_a_long_company_name_is_shortened_to_fit_the_column():
    """``trips.reference`` is String(40); a name longer than the column would
    otherwise fail the insert rather than the validation."""
    from app.services.trips import MAX_PREFIX_LEN, reference_prefix

    prefix = reference_prefix("A" * 200)
    assert len(prefix) == MAX_PREFIX_LEN
    assert len(f"{prefix}-{999999:04d}") <= 40


async def test_a_company_renaming_itself_gets_the_new_name_on_new_trips(
    client: AsyncClient, admin_headers, db
):
    """The prefix follows the organization's name, so a rename starts a fresh
    sequence. The old references stay exactly as issued — they are printed on
    CMRs that are already out of the office — and the unique constraint plus
    the create endpoint's retry keep the two books from colliding.
    """
    from sqlalchemy import select, update

    from app.models.organizations import Organization

    first = (await client.post("/api/trips", headers=admin_headers, json={"rate": 1})).json()
    assert first["reference"] == "Test Org-0001"

    org_id = (
        await db.execute(select(Organization.id).where(Organization.name == "Test Org"))
    ).scalar_one()
    await db.execute(
        update(Organization).where(Organization.id == org_id).values(name="Angren Tek")
    )
    await db.commit()

    second = (await client.post("/api/trips", headers=admin_headers, json={"rate": 1})).json()
    assert second["reference"].startswith("Angren Tek-")
    assert second["reference"] != first["reference"]

    # The reference already on paper did not move.
    listing = (await client.get("/api/trips", headers=admin_headers)).json()
    assert "Test Org-0001" in [t["reference"] for t in listing]
