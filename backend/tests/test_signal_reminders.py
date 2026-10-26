"""Reminding drivers until their phone reports, and the dispatcher every day.

The trip watcher says each silence once. That is right for the owner's chat,
but a driver who never switched sharing on, told once, stays invisible — so
the driver is reminded every few hours until a position arrives, and the
dispatcher gets one list a day of every truck still not reporting.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models.driver_messages import DriverMessage
from app.models.drivers import Driver, DriverAssignment
from app.models.organizations import Organization
from app.models.owner_alerts import AlertSeverity, TelegramAccount
from app.models.trucks import Truck, TruckLocation
from app.services import push
from app.services.owner_alerts import bus
from app.services.signal_reminders import run
from app.services.telegram import SendResult
from tests.conftest import awake_quiet_hours


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
    pushes: list[dict] = []

    async def _fake_push(db, tokens, *, title, body, data=None, transport=None):
        pushes.append({"title": title, "body": body})
        return push.PushOutcome(accepted=1)

    monkeypatch.setattr(push, "send_to_tokens", _fake_push)
    return pushes


async def _fleet(db, *, last_fix_ago: timedelta | None, with_driver: bool = True):
    org = Organization(name=f"Remind {uuid.uuid4().hex[:6]}")
    db.add(org)
    await db.flush()
    truck = Truck(org_id=org.id, name="10 422 TCA", plate_number="10 422 TCA")
    db.add(truck)
    await db.flush()
    driver = None
    if with_driver:
        driver = Driver(org_id=org.id, name="Anvar", license_number=f"L-{uuid.uuid4().hex[:8]}")
        db.add(driver)
        await db.flush()
        db.add(DriverAssignment(driver_id=driver.id, truck_id=truck.id))
    if last_fix_ago is not None:
        db.add(
            TruckLocation(
                truck_id=truck.id,
                latitude=41.3,
                longitude=69.2,
                recorded_at=datetime.now(timezone.utc) - last_fix_ago,
            )
        )
    db.add(
        TelegramAccount(
            org_id=org.id,
            token=uuid.uuid4().hex,
            chat_id="900002",
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


async def _age_messages(db, driver: Driver, by: timedelta) -> None:
    for message in await _inbox(db, driver):
        message.created_at = message.created_at - by
    await db.commit()


async def test_a_driver_who_never_connected_is_reminded_again_and_again(
    db, captured_sends, captured_pushes
):
    _org, _truck, driver = await _fleet(db, last_fix_ago=None)

    await run(db)
    await run(db)  # the next tick, inside the interval: nothing new
    assert len(captured_pushes) == 1
    assert "включите передачу геолокации" in captured_pushes[0]["body"]

    # The interval has passed and the phone still has not reported.
    await _age_messages(db, driver, timedelta(hours=settings.gps_reminder_hours, minutes=1))
    await run(db)
    assert len(captured_pushes) == 2
    assert len(await _inbox(db, driver)) == 2


async def test_a_reporting_truck_is_left_alone(db, captured_sends, captured_pushes):
    await _fleet(db, last_fix_ago=timedelta(minutes=5))
    assert await run(db) == 0
    assert captured_pushes == []
    assert captured_sends == []


async def test_a_lost_signal_tells_the_driver_how_long(db, captured_sends, captured_pushes):
    await _fleet(db, last_fix_ago=timedelta(hours=5))
    await run(db)
    assert "5 ч" in captured_pushes[0]["body"]


async def test_the_dispatcher_gets_one_list_a_day(db, captured_sends, captured_pushes):
    await _fleet(db, last_fix_ago=None)

    await run(db)
    await run(db)
    assert len(captured_sends) == 1
    text = captured_sends[0][1]
    assert "10 422 TCA" in text
    assert "Anvar" in text
    assert "ни разу не подключался" in text


async def test_a_truck_with_no_driver_reaches_only_the_dispatcher(
    db, captured_sends, captured_pushes
):
    await _fleet(db, last_fix_ago=None, with_driver=False)
    await run(db)
    assert captured_pushes == []
    assert "водитель не назначен" in captured_sends[0][1]


async def test_reminders_can_be_switched_off(db, captured_sends, captured_pushes, monkeypatch):
    monkeypatch.setattr(settings, "gps_reminder_hours", 0)
    await _fleet(db, last_fix_ago=None)
    assert await run(db) == 0
    assert captured_pushes == []
    assert captured_sends == []
