"""What the panel records about a driver: how to reach them, and ADR.

The three phone numbers are not a nicety. A dispatcher who cannot get through
on the cab SIM has, in this market, two other numbers to try — a personal
handset and a RU/KZ SIM bought for the leg past the border — and with one
column those lived in a notebook on someone's desk.
"""
from __future__ import annotations

from httpx import AsyncClient


async def _create(client: AsyncClient, headers: dict, **fields) -> dict:
    payload = {"name": "Anvar", "license_number": "AA1234567", **fields}
    res = await client.post("/api/drivers", headers=headers, json=payload)
    assert res.status_code == 200, res.text
    return res.json()


async def test_a_driver_holds_three_numbers(client: AsyncClient, admin_headers):
    driver = await _create(
        client,
        admin_headers,
        phone="+998901112233",
        phone2="+998933334455",
        phone3="+79161234567",
    )
    assert driver["phone"] == "+998901112233"
    assert driver["phone2"] == "+998933334455"
    assert driver["phone3"] == "+79161234567"

    listed = (await client.get("/api/drivers", headers=admin_headers)).json()
    assert listed[0]["phone3"] == "+79161234567"


async def test_the_extra_numbers_are_optional(client: AsyncClient, admin_headers):
    driver = await _create(client, admin_headers, phone="+998901112233")
    assert driver["phone2"] is None
    assert driver["phone3"] is None


async def test_a_second_number_can_be_added_later(client: AsyncClient, admin_headers):
    """The RU SIM is usually bought after the driver is already on file."""
    driver = await _create(client, admin_headers, phone="+998901112233")

    updated = await client.put(
        f"/api/drivers/{driver['id']}",
        headers=admin_headers,
        json={"phone2": "+79161234567"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["phone2"] == "+79161234567"
    # Untouched fields stay: a partial update is a patch, not a replacement.
    assert updated.json()["phone"] == "+998901112233"


async def test_adr_defaults_to_no(client: AsyncClient, admin_headers):
    """Assuming a driver is cleared for dangerous goods is the expensive way
    round to be wrong, so an unanswered question means "no"."""
    driver = await _create(client, admin_headers)
    assert driver["adr"] is False


async def test_adr_is_recorded_and_can_be_revoked(client: AsyncClient, admin_headers):
    driver = await _create(client, admin_headers, adr=True)
    assert driver["adr"] is True

    revoked = await client.put(
        f"/api/drivers/{driver['id']}", headers=admin_headers, json={"adr": False}
    )
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["adr"] is False


async def test_a_driver_needs_no_email_or_licence_expiry(client: AsyncClient, admin_headers):
    """Both were dropped from the form. Creating without them must still work —
    and must not quietly invent a value for either."""
    driver = await _create(client, admin_headers)
    assert driver["email"] is None
    assert driver["license_expiry"] is None
