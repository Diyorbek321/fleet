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


# ── Plate numbers belong to a fleet, not to the platform ──────────────


async def _signup(client, email: str, org_name: str) -> dict[str, str]:
    await client.post(
        "/api/auth/register",
        json={"email": email, "password": "password123", "org_name": org_name},
    )
    login = await client.post(
        "/api/auth/login", json={"email": email, "password": "password123"}
    )
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def test_two_fleets_may_hold_the_same_plate(client: AsyncClient):
    """A plate that exists somewhere on the platform is not the caller's problem.

    It also must not be *reported* to them: telling one company that a plate is
    taken discloses that a competitor on the same platform runs that truck.
    """
    a = await _signup(client, "plate-a@org.com", "Plate Org A")
    b = await _signup(client, "plate-b@org.com", "Plate Org B")

    first = await client.post(
        "/api/trucks", headers=a, json={"name": "A truck", "plate_number": "01A123BC"}
    )
    assert first.status_code in (200, 201), first.text

    second = await client.post(
        "/api/trucks", headers=b, json={"name": "B truck", "plate_number": "01A123BC"}
    )
    assert second.status_code in (200, 201), (
        f"Org B was blocked by Org A's plate: {second.status_code} {second.text}"
    )


async def test_the_same_plate_twice_in_one_fleet_is_a_conflict(
    client: AsyncClient, admin_headers
):
    """Within a fleet a plate still identifies exactly one truck."""
    payload = {"name": "Alpha", "plate_number": "01A999ZZ"}
    assert (await client.post("/api/trucks", headers=admin_headers, json=payload)).status_code in (200, 201)

    duplicate = await client.post("/api/trucks", headers=admin_headers, json=payload)
    assert duplicate.status_code == 409, duplicate.text
    assert "01A999ZZ" in duplicate.json()["detail"]


async def test_renaming_a_plate_onto_a_sibling_is_a_conflict(
    client: AsyncClient, admin_headers
):
    first = await client.post(
        "/api/trucks", headers=admin_headers, json={"name": "One", "plate_number": "01A111AA"}
    )
    second = await client.post(
        "/api/trucks", headers=admin_headers, json={"name": "Two", "plate_number": "01A222BB"}
    )

    clash = await client.put(
        f"/api/trucks/{second.json()['id']}",
        headers=admin_headers,
        json={"plate_number": "01A111AA"},
    )
    assert clash.status_code == 409, clash.text

    # And a truck keeping its own plate through an unrelated edit is not a clash.
    same = await client.put(
        f"/api/trucks/{first.json()['id']}",
        headers=admin_headers,
        json={"name": "One renamed", "plate_number": "01A111AA"},
    )
    assert same.status_code == 200, same.text


# ── The rig: two vehicles, one row ───────────────────────────────────────


async def test_a_rig_records_both_makes_and_its_capacity_class(
    client: AsyncClient, admin_headers
):
    """A tractor and its semi-trailer are bought, serviced and replaced apart.

    Held as one free-text "model" they could not be grouped by in any report,
    and the capacity a load is booked against was nowhere at all.
    """
    created = (
        await client.post(
            "/api/trucks",
            headers=admin_headers,
            json={
                "name": "Alpha",
                "plate_number": "AA-77",
                "tractor_brand": "MAN",
                "trailer_brand": "Schmitz",
                "trailer_volume": "mega",
            },
        )
    ).json()

    assert created["tractor_brand"] == "MAN"
    assert created["trailer_brand"] == "Schmitz"
    assert created["trailer_volume"] == "mega"

    fetched = (await client.get(f"/api/trucks/{created['id']}", headers=admin_headers)).json()
    assert fetched["trailer_volume"] == "mega"


async def test_a_tractor_with_no_trailer_has_no_capacity_class(
    client: AsyncClient, admin_headers
):
    """Defaulting one would make the truck bookable for a load it cannot take."""
    created = (
        await client.post(
            "/api/trucks", headers=admin_headers, json={"name": "B", "plate_number": "BB-01"}
        )
    ).json()
    assert created["trailer_volume"] is None
    assert created["tractor_brand"] is None


async def test_capacity_class_is_a_closed_set(client: AsyncClient, admin_headers):
    """"standart" and "mega" are what the market quotes; free text here would
    be ungroupable the moment two dispatchers spelled it differently."""
    res = await client.post(
        "/api/trucks",
        headers=admin_headers,
        json={"name": "C", "plate_number": "CC-01", "trailer_volume": "enormous"},
    )
    assert res.status_code == 422


async def test_a_trailer_can_be_swapped_onto_a_tractor(client: AsyncClient, admin_headers):
    created = (
        await client.post(
            "/api/trucks",
            headers=admin_headers,
            json={
                "name": "D",
                "plate_number": "DD-01",
                "trailer_brand": "Koegel",
                "trailer_volume": "standart",
            },
        )
    ).json()

    updated = await client.put(
        f"/api/trucks/{created['id']}",
        headers=admin_headers,
        json={"trailer_brand": "Schmitz", "trailer_volume": "mega"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["trailer_brand"] == "Schmitz"
    assert updated.json()["trailer_volume"] == "mega"


# ── "offline" is a radio silence, not a decision ──────────────────────
#
# The two used to be one column: a truck with no GPS fix read as `offline`,
# and the panel took that to mean "switched off" — so every truck was born
# disabled, invisible on the map and missing from the fuel and service
# pickers until its tracker happened to send a first ping.


async def test_a_new_truck_is_enabled_although_it_has_no_gps_yet(
    client: AsyncClient, admin_headers
):
    created = (
        await client.post(
            "/api/trucks", headers=admin_headers, json={"name": "E", "plate_number": "EE-01"}
        )
    ).json()

    assert created["status"] == "offline"  # no tracker has reported in
    assert created["is_enabled"] is True   # but the dispatcher runs this truck


async def test_taking_a_truck_out_of_service_leaves_its_status_alone(
    client: AsyncClient, admin_headers
):
    created = (
        await client.post(
            "/api/trucks", headers=admin_headers, json={"name": "F", "plate_number": "FF-01"}
        )
    ).json()
    await client.put(
        f"/api/trucks/{created['id']}", headers=admin_headers, json={"status": "moving"}
    )

    disabled = await client.put(
        f"/api/trucks/{created['id']}", headers=admin_headers, json={"is_enabled": False}
    )
    assert disabled.status_code == 200, disabled.text
    assert disabled.json()["is_enabled"] is False
    assert disabled.json()["status"] == "moving"


async def test_a_gps_ping_does_not_put_a_parked_truck_back_in_service(
    client: AsyncClient, admin_headers
):
    """A tracker left powered in the yard must not re-enable a truck the
    dispatcher deliberately took off the board."""
    created = (
        await client.post(
            "/api/trucks", headers=admin_headers, json={"name": "G", "plate_number": "GG-01"}
        )
    ).json()
    await client.put(
        f"/api/trucks/{created['id']}", headers=admin_headers, json={"is_enabled": False}
    )

    pinged = await client.put(
        f"/api/trucks/{created['id']}", headers=admin_headers, json={"status": "stopped"}
    )
    assert pinged.json()["is_enabled"] is False

    listed = (await client.get("/api/trucks", headers=admin_headers)).json()
    assert [t["is_enabled"] for t in listed] == [False]


async def test_truck_details_carry_the_enabled_flag(client: AsyncClient, admin_headers):
    created = (
        await client.post(
            "/api/trucks", headers=admin_headers, json={"name": "H", "plate_number": "HH-01"}
        )
    ).json()

    detail = await client.get(f"/api/trucks/{created['id']}", headers=admin_headers)
    assert detail.json()["is_enabled"] is True


# ── the plate is the name, and insurance has a date ────────────────────


async def test_a_truck_can_be_added_by_plate_alone(client: AsyncClient, admin_headers):
    """The form no longer asks for a separate name; every screen that shows
    one gets the plate instead of a blank."""
    res = await client.post("/api/trucks", headers=admin_headers, json={"plate_number": "01A777AA"})
    assert res.status_code == 200, res.text
    assert res.json()["name"] == "01A777AA"


async def test_a_name_that_was_the_plate_follows_a_plate_correction(
    client: AsyncClient, admin_headers
):
    created = (
        await client.post("/api/trucks", headers=admin_headers, json={"plate_number": "01A777AB"})
    ).json()
    res = await client.put(
        f"/api/trucks/{created['id']}", headers=admin_headers, json={"plate_number": "01A777AC"}
    )
    assert res.json()["name"] == "01A777AC"


async def test_insurance_expiry_is_stored_and_editable(client: AsyncClient, admin_headers):
    created = (
        await client.post(
            "/api/trucks",
            headers=admin_headers,
            json={"plate_number": "01A888AA", "insurance_expiry": "2027-03-01"},
        )
    ).json()
    assert created["insurance_expiry"] == "2027-03-01"

    updated = await client.put(
        f"/api/trucks/{created['id']}", headers=admin_headers, json={"insurance_expiry": None}
    )
    assert updated.json()["insurance_expiry"] is None
