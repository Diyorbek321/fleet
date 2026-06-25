"""CarGoRuqsat border-queue tracking (`/api/me/queue/*`).

The external site is faked via a dependency override so we test our own logic:
watch lifecycle, status mapping, and change-detection / notify gating.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

import pytest_asyncio
from httpx import AsyncClient

from app.main import app
from app.services.cgr import BookingRecord, CgrStatus, get_cgr_client, normalize_status


class FakeCgrClient:
    """Returns whatever record is set on it; records lookups."""

    def __init__(self) -> None:
        self.record: Optional[BookingRecord] = None
        self.calls: list[str] = []

    async def lookup_truck(self, plate: str) -> Optional[BookingRecord]:
        self.calls.append(plate)
        return self.record


@pytest_asyncio.fixture
async def fake_cgr():
    fake = FakeCgrClient()
    app.dependency_overrides[get_cgr_client] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_cgr_client, None)


async def _assign_truck(client: AsyncClient, admin_headers, driver_id: str, plate: str = "777ABC01") -> str:
    truck = (
        await client.post(
            "/api/trucks",
            headers=admin_headers,
            json={"name": "Q-Truck", "plate_number": plate},
        )
    ).json()
    await client.post(
        f"/api/drivers/{driver_id}/assign",
        headers=admin_headers,
        json={"truck_id": truck["id"]},
    )
    return plate


def test_status_mapping():
    assert normalize_status("В очереди") is CgrStatus.in_queue
    assert normalize_status("Пересёк пункт пропуска") is CgrStatus.crossed
    assert normalize_status("Пропуск отозван") is CgrStatus.revoked
    assert normalize_status("что-то новое") is CgrStatus.unknown


async def test_queue_requires_assigned_truck(client: AsyncClient, driver_login, fake_cgr):
    res = await client.get("/api/me/queue/status", headers=driver_login["headers"])
    assert res.status_code == 409  # no truck assigned


async def test_queue_status_no_booking(client: AsyncClient, admin_headers, driver_login, fake_cgr):
    await _assign_truck(client, admin_headers, driver_login["driver_id"])
    fake_cgr.record = None
    res = await client.get("/api/me/queue/status", headers=driver_login["headers"])
    assert res.status_code == 200
    assert res.json() is None
    assert fake_cgr.calls == ["777ABC01"]


async def test_queue_status_with_booking(client: AsyncClient, admin_headers, driver_login, fake_cgr):
    plate = await _assign_truck(client, admin_headers, driver_login["driver_id"])
    fake_cgr.record = BookingRecord(
        plate=plate,
        checkpoint="Нур Жолы - Хоргос",
        queue_at=datetime(2026, 6, 20, 14, 30),
        status=CgrStatus.in_queue,
        raw_status="В очереди",
    )
    res = await client.get("/api/me/queue/status", headers=driver_login["headers"])
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "in_queue"
    assert body["checkpoint"] == "Нур Жолы - Хоргос"


async def test_watch_lifecycle(client: AsyncClient, admin_headers, driver_login, fake_cgr):
    h = driver_login["headers"]
    await _assign_truck(client, admin_headers, driver_login["driver_id"])

    assert (await client.get("/api/me/queue/watch", headers=h)).json() is None

    created = await client.put(
        "/api/me/queue/watch",
        headers=h,
        json={"checkpoint": "Нур Жолы - Хоргос", "country": "China"},
    )
    assert created.status_code == 200, created.text
    assert created.json()["checkpoint"] == "Нур Жолы - Хоргос"
    assert created.json()["plate"] == "777ABC01"

    # Idempotent update (no duplicate row).
    again = await client.put(
        "/api/me/queue/watch", headers=h, json={"checkpoint": "Жайсан - Сагарчин"}
    )
    assert again.status_code == 200
    assert again.json()["id"] == created.json()["id"]
    assert again.json()["checkpoint"] == "Жайсан - Сагарчин"

    stop = await client.delete("/api/me/queue/watch", headers=h)
    assert stop.status_code == 200
    assert (await client.get("/api/me/queue/watch", headers=h)).json() is None
    assert (await client.delete("/api/me/queue/watch", headers=h)).status_code == 404


async def test_refresh_change_detection(client: AsyncClient, admin_headers, driver_login, fake_cgr):
    h = driver_login["headers"]
    plate = await _assign_truck(client, admin_headers, driver_login["driver_id"])
    await client.put("/api/me/queue/watch", headers=h, json={"checkpoint": "CP", "country": "China"})

    # First refresh: booking appears → changed True.
    fake_cgr.record = BookingRecord(plate, "CP", datetime(2026, 6, 20, 9, 0), CgrStatus.in_queue, "В очереди")
    r1 = await client.post("/api/me/queue/refresh", headers=h)
    assert r1.status_code == 200
    assert r1.json()["changed"] is True
    assert r1.json()["status"]["status"] == "in_queue"

    # Same status again → not changed (no re-notify).
    r2 = await client.post("/api/me/queue/refresh", headers=h)
    assert r2.json()["changed"] is False

    # Status moves on → changed True again.
    fake_cgr.record = BookingRecord(plate, "CP", datetime(2026, 6, 20, 9, 0), CgrStatus.crossed, "Пересёк пункт пропуска")
    r3 = await client.post("/api/me/queue/refresh", headers=h)
    assert r3.json()["changed"] is True
    assert r3.json()["status"]["status"] == "crossed"


async def test_handoff_url(client: AsyncClient, admin_headers, driver_login, fake_cgr):
    h = driver_login["headers"]
    await _assign_truck(client, admin_headers, driver_login["driver_id"], plate="555XYZ02")
    await client.put("/api/me/queue/watch", headers=h, json={"checkpoint": "Хоргос"})
    res = await client.get("/api/me/queue/handoff", headers=h)
    assert res.status_code == 200
    url = res.json()["url"]
    assert url.startswith("https://cgr.qoldau.kz/ru/start")
    assert "555XYZ02" in url
