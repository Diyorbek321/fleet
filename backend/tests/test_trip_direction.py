"""Which way a run goes, and so which country's customs it clears.

Every run on these corridors clears customs in the country it is going to: a
UZ→RU load at a Russian terminal, a RU→UZ load at an Uzbek one. The customs
post was a free-text line with no country, so the order sheet could not say
which side of the border it meant. The direction is recorded on the trip and
the customs post is read against it.
"""
from __future__ import annotations

from httpx import AsyncClient


async def _create(client: AsyncClient, headers: dict, **fields):
    return await client.post("/api/trips", headers=headers, json=fields)


async def test_a_trip_records_its_direction_and_customs_post(client: AsyncClient, admin_headers):
    res = await _create(
        client, admin_headers, direction="uz_ru", customs_point="Тюменский таможенный пост"
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["direction"] == "uz_ru"
    assert body["customs_point"] == "Тюменский таможенный пост"

    listed = (await client.get("/api/trips", headers=admin_headers)).json()
    assert listed[0]["direction"] == "uz_ru"


async def test_the_direction_can_be_changed(client: AsyncClient, admin_headers):
    trip = (await _create(client, admin_headers, direction="uz_ru")).json()
    res = await client.put(
        f"/api/trips/{trip['id']}",
        headers=admin_headers,
        json={"direction": "ru_uz", "customs_point": "Ташкент, Чукурсай"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["direction"] == "ru_uz"
    assert res.json()["customs_point"] == "Ташкент, Чукурсай"


async def test_a_trip_without_a_direction_still_saves(client: AsyncClient, admin_headers):
    """Trips created before the field existed have none, and must stay editable."""
    res = await _create(client, admin_headers, origin_name="Ангрен")
    assert res.status_code == 200, res.text
    assert res.json()["direction"] is None


async def test_an_unknown_direction_is_refused(client: AsyncClient, admin_headers):
    res = await _create(client, admin_headers, direction="uz_kz")
    assert res.status_code == 422
