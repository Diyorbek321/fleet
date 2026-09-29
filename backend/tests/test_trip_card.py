"""The status a dispatcher copies out of the panel and pastes to a customer.

Cargo owners who are not on the Telegram bot still ask "where is my load" in a
chat, and the dispatcher's answer used to be retyped by hand from three screens.
The copied text is the bot's own card — same lines, same order — as plain text,
plus the two things a hand-pasted message needs that the bot's does not: the
checkpoint in words, and how old the position is.
"""
from __future__ import annotations

from datetime import datetime, timezone

from httpx import AsyncClient

from app.models.trucks import TruckLocation


async def _truck(client: AsyncClient, headers: dict) -> str:
    res = await client.post(
        "/api/trucks", headers=headers, json={"name": "MAN", "plate_number": "10 422 TCA"}
    )
    assert res.status_code == 200, res.text
    return res.json()["id"]


async def _trip(client: AsyncClient, headers: dict, truck_id: str) -> str:
    res = await client.post(
        "/api/trips",
        headers=headers,
        json={
            "truck_id": truck_id,
            "origin_name": "Ангрен",
            "destination_name": "Тюмень",
            "cargo_description": "Уголь & кокс",
        },
    )
    assert res.status_code == 200, res.text
    return res.json()["id"]


async def test_the_card_is_plain_text_with_the_checkpoint(client: AsyncClient, admin_headers, db):
    import uuid

    truck_id = await _truck(client, admin_headers)
    trip_id = await _trip(client, admin_headers, truck_id)
    res = await client.post(
        f"/api/trips/{trip_id}/advance",
        headers=admin_headers,
        json={"stage": "arrived_border", "stage_place": "uz_kz"},
    )
    assert res.status_code == 200, res.text

    db.add(
        TruckLocation(
            truck_id=uuid.UUID(truck_id),
            latitude=41.3,
            longitude=69.2,
            speed=0,
            recorded_at=datetime(2026, 9, 25, 14, 10, tzinfo=timezone.utc),
        )
    )
    await db.commit()

    res = await client.get(f"/api/trips/{trip_id}/card", headers=admin_headers)
    assert res.status_code == 200, res.text
    text = res.json()["text"]

    assert "Маршрут: Ангрен — Тюмень" in text
    assert "ТС: 10 422 TCA" in text
    assert "Статус: На границе УЗБ–КЗ" in text
    # Escaped for Telegram, unescaped for a paste.
    assert "Груз: Уголь & кокс" in text
    # The map link survives as a URL instead of vanishing with its tag.
    assert "https://maps.google.com/?q=41.3,69.2" in text
    # Local time: 14:10 UTC is 19:10 in Tashkent.
    assert "25.09 19:10" in text
    assert "<" not in text and "&amp;" not in text


async def test_a_trip_with_no_checkpoint_or_position_still_copies(client: AsyncClient, admin_headers):
    truck_id = await _truck(client, admin_headers)
    trip_id = await _trip(client, admin_headers, truck_id)

    res = await client.get(f"/api/trips/{trip_id}/card", headers=admin_headers)
    assert res.status_code == 200, res.text
    text = res.json()["text"]
    assert "Статус" not in text
    assert "местоположение пока не определено" in text


async def test_another_fleets_trip_card_is_not_readable(client: AsyncClient, admin_headers):
    truck_id = await _truck(client, admin_headers)
    trip_id = await _trip(client, admin_headers, truck_id)
    await client.post(
        "/api/auth/register",
        json={"email": "rival@test.com", "password": "password123", "org_name": "Rival"},
    )
    rival = await client.post(
        "/api/auth/login", json={"email": "rival@test.com", "password": "password123"}
    )
    headers = {"Authorization": f"Bearer {rival.json()['access_token']}"}

    res = await client.get(f"/api/trips/{trip_id}/card", headers=headers)
    assert res.status_code == 404
