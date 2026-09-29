"""Messages to a driver's phone: from the dispatcher, and from the GPS watcher.

The watcher's promises are the ones worth pinning down: only trucks on a
running trip, only after a day of silence, and only once — a driver whose phone
buzzes every fifteen minutes about the same dead GPS uninstalls the app.
"""
from __future__ import annotations

from tests.conftest import awake_quiet_hours

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.models.driver_messages import DriverMessage
from app.models.drivers import Driver
from app.models.enums import TripStatus
from app.models.organizations import Organization
from app.models.owner_alerts import AlertSeverity, TelegramAccount
from app.models.trips import Trip
from app.models.trucks import Truck, TruckLocation
from app.services import push
from app.services.owner_alerts import bus
from app.services.owner_alerts.gps import run
from app.services.telegram import SendResult


@pytest.fixture
def captured_sends(monkeypatch) -> list[tuple[str, str]]:
    monkeypatch.setattr(settings, "telegram_bot_token", "TEST:token", raising=False)
    sends: list[tuple[str, str]] = []

    async def _fake_send(chat_id, text, *, disable_notification=False):
        sends.append((chat_id, text))
        return SendResult(ok=True, status_code=200)

    monkeypatch.setattr(bus, "send_message", _fake_send)
    return sends


@pytest.fixture
def captured_pushes(monkeypatch) -> list[dict]:
    """Stand in for Expo: every driver has exactly one phone that takes it."""
    pushes: list[dict] = []

    async def _fake_push(db, tokens, *, title, body, data=None, transport=None):
        pushes.append({"title": title, "body": body, "data": data})
        return push.PushOutcome(accepted=1)

    monkeypatch.setattr(push, "send_to_tokens", _fake_push)
    return pushes


# ── Dispatcher → driver ──────────────────────────────────────────────────


async def test_dispatcher_message_lands_in_the_drivers_inbox(
    client: AsyncClient, admin_headers, driver_login, captured_pushes
):
    res = await client.post(
        f"/api/drivers/{driver_login['driver_id']}/messages",
        headers=admin_headers,
        json={"body": "  Позвоните в офис  "},
    )
    assert res.status_code == 201, res.text
    sent = res.json()
    assert sent["kind"] == "dispatcher"
    assert sent["title"] == "Сообщение от диспетчера"
    assert sent["body"] == "Позвоните в офис"
    assert sent["devices_delivered"] == 1
    assert captured_pushes[0]["data"] == {"kind": "message", "message_id": sent["id"]}

    inbox = (await client.get("/api/me/messages", headers=driver_login["headers"])).json()
    assert [m["id"] for m in inbox] == [sent["id"]]
    assert inbox[0]["read_at"] is None

    history = (
        await client.get(
            f"/api/drivers/{driver_login['driver_id']}/messages", headers=admin_headers
        )
    ).json()
    assert [m["id"] for m in history] == [sent["id"]]


async def test_a_driver_without_a_phone_still_gets_the_message_in_the_inbox(
    client: AsyncClient, admin_headers, driver_login
):
    """No push token registered: nothing buzzes, and the panel is told so."""
    res = await client.post(
        f"/api/drivers/{driver_login['driver_id']}/messages",
        headers=admin_headers,
        json={"title": "Срочно", "body": "Проверьте GPS"},
    )
    assert res.status_code == 201
    assert res.json()["devices_delivered"] == 0
    assert res.json()["title"] == "Срочно"


async def test_a_blank_message_is_refused(client: AsyncClient, admin_headers, driver_login):
    res = await client.post(
        f"/api/drivers/{driver_login['driver_id']}/messages",
        headers=admin_headers,
        json={"body": "   "},
    )
    assert res.status_code == 422


async def test_a_driver_cannot_send_messages(client: AsyncClient, driver_login):
    res = await client.post(
        f"/api/drivers/{driver_login['driver_id']}/messages",
        headers=driver_login["headers"],
        json={"body": "hi"},
    )
    assert res.status_code == 403


async def test_another_companys_driver_is_not_found(client: AsyncClient, admin_headers):
    res = await client.post(
        f"/api/drivers/{uuid.uuid4()}/messages", headers=admin_headers, json={"body": "hi"}
    )
    assert res.status_code == 404


async def test_marking_read_stamps_once(client: AsyncClient, admin_headers, driver_login):
    sent = (
        await client.post(
            f"/api/drivers/{driver_login['driver_id']}/messages",
            headers=admin_headers,
            json={"body": "hi"},
        )
    ).json()
    first = await client.post(
        f"/api/me/messages/{sent['id']}/read", headers=driver_login["headers"]
    )
    assert first.status_code == 200
    assert first.json()["read_at"] is not None
    second = await client.post(
        f"/api/me/messages/{sent['id']}/read", headers=driver_login["headers"]
    )
    assert second.json()["read_at"] == first.json()["read_at"]

    missing = await client.post(
        f"/api/me/messages/{uuid.uuid4()}/read", headers=driver_login["headers"]
    )
    assert missing.status_code == 404


# ── The phone's GPS switch ───────────────────────────────────────────────


async def _assigned_truck(client: AsyncClient, admin_headers, driver_login) -> str:
    truck = (
        await client.post(
            "/api/trucks", headers=admin_headers, json={"name": "T", "plate_number": "GPS-01"}
        )
    ).json()
    res = await client.post(
        f"/api/drivers/{driver_login['driver_id']}/assign",
        headers=admin_headers,
        json={"truck_id": truck["id"]},
    )
    assert res.status_code in (200, 201), res.text
    return truck["id"]


async def test_gps_off_is_stamped_once_and_cleared_by_a_fix(
    client: AsyncClient, admin_headers, driver_login
):
    truck_id = await _assigned_truck(client, admin_headers, driver_login)
    headers = driver_login["headers"]

    first = (await client.post("/api/me/gps-status", headers=headers, json={"enabled": False})).json()
    again = (await client.post("/api/me/gps-status", headers=headers, json={"enabled": False})).json()
    # Moving the stamp forward would restart the watcher's grace period forever.
    assert first["gps_disabled_at"] is not None
    assert again["gps_disabled_at"] == first["gps_disabled_at"]

    truck = (await client.get(f"/api/trucks/{truck_id}", headers=admin_headers)).json()
    assert truck["gps_disabled_at"] is not None

    await client.post(
        "/api/me/location", headers=headers, json={"latitude": 41.3, "longitude": 69.2}
    )
    truck = (await client.get(f"/api/trucks/{truck_id}", headers=admin_headers)).json()
    assert truck["gps_disabled_at"] is None


async def test_gps_on_clears_the_stamp(client: AsyncClient, admin_headers, driver_login):
    await _assigned_truck(client, admin_headers, driver_login)
    headers = driver_login["headers"]
    await client.post("/api/me/gps-status", headers=headers, json={"enabled": False})
    res = (await client.post("/api/me/gps-status", headers=headers, json={"enabled": True})).json()
    assert res["gps_disabled_at"] is None


# ── The watcher ──────────────────────────────────────────────────────────


async def _fleet_on_trip(
    db,
    *,
    silent_for: timedelta | None = timedelta(hours=25),
    status: TripStatus = TripStatus.en_route,
    with_driver: bool = True,
) -> tuple[Organization, Truck, Driver | None]:
    org = Organization(name="GPS Co")
    db.add(org)
    await db.flush()
    truck = Truck(org_id=org.id, name="01A123BC", plate_number="01A123BC")
    driver = (
        Driver(org_id=org.id, name="Anvar", license_number=f"LIC-{uuid.uuid4().hex[:8]}")
        if with_driver
        else None
    )
    db.add(truck)
    if driver:
        db.add(driver)
    await db.flush()
    if silent_for is not None:
        db.add(
            TruckLocation(
                truck_id=truck.id,
                latitude=41.3,
                longitude=69.2,
                recorded_at=datetime.now(timezone.utc) - silent_for,
            )
        )
    db.add(
        Trip(
            org_id=org.id,
            reference="TR-2026-000042",
            truck_id=truck.id,
            driver_id=driver.id if driver else None,
            status=status,
        )
    )
    db.add(
        TelegramAccount(
            org_id=org.id,
            token=uuid.uuid4().hex,
            chat_id="900001",
            min_severity=AlertSeverity.info,
            muted_kinds=[],
            **awake_quiet_hours(),
        )
    )
    await db.commit()
    return org, truck, driver


async def _inbox(db, driver: Driver) -> list[DriverMessage]:
    rows = await db.execute(select(DriverMessage).where(DriverMessage.driver_id == driver.id))
    return list(rows.scalars().all())


async def test_a_day_of_silence_tells_the_driver_and_the_dispatcher_once(
    db, captured_sends, captured_pushes
):
    _org, _truck, driver = await _fleet_on_trip(db)

    assert await run(db) == 1
    assert await run(db) == 0  # the next tick: same silence, nothing new

    assert len(captured_sends) == 1
    assert "01A123BC - Anvar - TR-2026-000042 — нет GPS 1 дн. 1 ч" in captured_sends[0][1]
    assert "Водителю отправлено уведомление" in captured_sends[0][1]

    assert len(captured_pushes) == 1
    assert "01A123BC" in captured_pushes[0]["body"]
    inbox = await _inbox(db, driver)
    assert len(inbox) == 1
    assert inbox[0].kind == "gps_silent"
    assert inbox[0].devices_delivered == 1


async def test_a_new_silence_after_the_truck_came_back_is_news_again(
    db, captured_sends, captured_pushes
):
    _org, truck, driver = await _fleet_on_trip(db)
    await run(db)

    loc = (
        await db.execute(select(TruckLocation).where(TruckLocation.truck_id == truck.id))
    ).scalar_one()
    loc.recorded_at = datetime.now(timezone.utc) - timedelta(hours=30)
    await db.commit()

    await run(db)
    assert len(captured_sends) == 2
    assert len(await _inbox(db, driver)) == 2


@pytest.mark.parametrize(
    "silent_for,status",
    [
        (timedelta(hours=20), TripStatus.en_route),  # not a day yet
        (timedelta(hours=25), TripStatus.planned),  # not on the road
        (timedelta(hours=25), TripStatus.delivered),  # finished
        (timedelta(days=20), TripStatus.en_route),  # stale bookkeeping
    ],
)
async def test_quiet_trucks_off_the_road_are_left_alone(
    db, captured_sends, captured_pushes, silent_for, status
):
    await _fleet_on_trip(db, silent_for=silent_for, status=status)
    assert await run(db) == 0
    assert captured_sends == []
    assert captured_pushes == []


async def test_a_trip_without_a_driver_still_reaches_the_dispatcher(
    db, captured_sends, captured_pushes
):
    await _fleet_on_trip(db, with_driver=False)
    assert await run(db) == 1
    assert "уведомить некого" in captured_sends[0][1]
    assert captured_pushes == []


async def test_gps_switched_off_reaches_the_dispatcher_after_the_grace_period(
    db, captured_sends, captured_pushes
):
    _org, truck, _driver = await _fleet_on_trip(db, silent_for=timedelta(minutes=1))

    truck.gps_disabled_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    await db.commit()
    assert await run(db) == 0  # a driver toggling it for a minute is not news

    truck.gps_disabled_at = datetime.now(timezone.utc) - timedelta(minutes=20)
    await db.commit()
    assert await run(db) == 1
    assert await run(db) == 0
    assert "GPS выключен на телефоне" in captured_sends[0][1]
    # The phone already showed the driver its own notification.
    assert captured_pushes == []
