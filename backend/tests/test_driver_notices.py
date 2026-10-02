"""Automatic notices on the driver's phone.

The promises: a driver hears about a trip the moment it is theirs, hears what
changed and nothing else, is reminded about loading and the CMR at the right
time and only once, and is warned about the truck's service and expiring
papers before the dispatcher has to chase them.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models.driver_messages import DriverMessage
from app.models.drivers import Driver, DriverAssignment
from app.models.enums import ServiceType, TripStatus
from app.models.maintenance import ServiceInterval
from app.models.organizations import Organization
from app.models.trips import Trip, TripDocument
from app.models.trucks import Truck
from app.services import driver_notices, push
from app.services.driver_notices import run

# 19:00 in Tashkent — past the evening-before hour, so "tomorrow" reminders fire.
EVENING = datetime(2026, 10, 1, 14, 0, tzinfo=timezone.utc)
# 10:00 in Tashkent — past the morning-of hour, before the evening one.
MORNING = datetime(2026, 10, 1, 5, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def no_real_push(monkeypatch):
    async def _fake(db, tokens, *, title, body, data=None, transport=None):
        return push.PushOutcome(accepted=len(tokens))

    monkeypatch.setattr(push, "send_to_tokens", _fake)


async def _inbox(client: AsyncClient, driver_login) -> list[dict]:
    return (await client.get("/api/me/messages", headers=driver_login["headers"])).json()


# ── Trip events ──────────────────────────────────────────────────────────


async def test_a_trip_given_to_a_driver_reaches_their_phone(
    client: AsyncClient, admin_headers, driver_login
):
    await client.post(
        "/api/trips",
        headers=admin_headers,
        json={
            "driver_id": driver_login["driver_id"],
            "origin_name": "Елабуга",
            "destination_name": "Ташкент",
            "loading_address": "улица Ш-3",
            "scheduled_start": "2026-10-02T06:00:00Z",
        },
    )
    inbox = await _inbox(client, driver_login)
    assert len(inbox) == 1
    assert inbox[0]["kind"] == "trip_assigned"
    assert "Елабуга → Ташкент" in inbox[0]["body"]
    assert "Погрузка: 02.10." in inbox[0]["body"]
    assert "улица Ш-3" in inbox[0]["body"]


async def test_an_edit_tells_the_driver_what_moved_and_nothing_else(
    client: AsyncClient, admin_headers, driver_login
):
    trip = (
        await client.post(
            "/api/trips",
            headers=admin_headers,
            json={"driver_id": driver_login["driver_id"], "loading_address": "Старый адрес"},
        )
    ).json()

    await client.put(
        f"/api/trips/{trip['id']}",
        headers=admin_headers,
        json={"loading_address": "Новый адрес", "cargo_weight_kg": 22000, "rate": 999},
    )
    changed = [m for m in await _inbox(client, driver_login) if m["kind"] == "trip_changed"]
    assert len(changed) == 1
    assert "• Адрес погрузки: Новый адрес" in changed[0]["body"]
    assert "• Вес груза: 22 тн" in changed[0]["body"]
    assert "999" not in changed[0]["body"]  # the rate is not the driver's business

    # Money alone is not news to the driver.
    await client.put(f"/api/trips/{trip['id']}", headers=admin_headers, json={"rate": 1500})
    assert len([m for m in await _inbox(client, driver_login) if m["kind"] == "trip_changed"]) == 1


async def test_a_driver_put_on_an_existing_trip_hears_new_trip_not_changes(
    client: AsyncClient, admin_headers, driver_login
):
    trip = (await client.post("/api/trips", headers=admin_headers, json={})).json()
    await client.put(
        f"/api/trips/{trip['id']}",
        headers=admin_headers,
        json={"driver_id": driver_login["driver_id"], "loading_address": "X"},
    )
    assert [m["kind"] for m in await _inbox(client, driver_login)] == ["trip_assigned"]


# ── Reminders (scheduler) ────────────────────────────────────────────────


async def _fleet(db) -> tuple[Organization, Truck, Driver]:
    org = Organization(name=f"Notice Co {uuid.uuid4().hex[:6]}")
    db.add(org)
    await db.flush()
    truck = Truck(org_id=org.id, name="T", plate_number="01A123BC", mileage=100_000)
    driver = Driver(org_id=org.id, name="Anvar", license_number=f"LIC-{uuid.uuid4().hex[:8]}")
    db.add_all([truck, driver])
    await db.flush()
    db.add(DriverAssignment(driver_id=driver.id, truck_id=truck.id))
    await db.commit()
    return org, truck, driver


async def _messages(db, driver: Driver, kind: str) -> list[DriverMessage]:
    rows = await db.execute(
        select(DriverMessage).where(DriverMessage.driver_id == driver.id, DriverMessage.kind == kind)
    )
    return list(rows.scalars().all())


async def _trip(db, org, truck, driver, **fields) -> Trip:
    trip = Trip(
        org_id=org.id,
        reference=f"Notice-{uuid.uuid4().hex[:4]}-0026",
        truck_id=truck.id,
        driver_id=driver.id,
        origin_name="Елабуга",
        destination_name="Ташкент",
        **fields,
    )
    db.add(trip)
    await db.commit()
    return trip


async def test_loading_tomorrow_is_reminded_in_the_evening_once(db):
    org, truck, driver = await _fleet(db)
    await _trip(db, org, truck, driver, status=TripStatus.planned,
                scheduled_start=datetime(2026, 10, 2, 4, 0, tzinfo=timezone.utc),
                loading_address="улица Ш-3")

    await run(db, now=MORNING)  # 10:00 the day before: too early
    assert await _messages(db, driver, "loading_reminder") == []

    await run(db, now=EVENING)
    await run(db, now=EVENING + timedelta(minutes=15))
    reminders = await _messages(db, driver, "loading_reminder")
    assert len(reminders) == 1
    assert reminders[0].title == "📅 Завтра погрузка"
    assert "улица Ш-3" in reminders[0].body


async def test_loading_today_is_reminded_in_the_morning(db):
    org, truck, driver = await _fleet(db)
    await _trip(db, org, truck, driver, status=TripStatus.draft,
                scheduled_start=datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc))
    await run(db, now=MORNING)
    reminders = await _messages(db, driver, "loading_reminder")
    assert [r.title for r in reminders] == ["📅 Сегодня погрузка"]


async def test_a_trip_already_on_the_road_gets_no_loading_reminder(db):
    org, truck, driver = await _fleet(db)
    await _trip(db, org, truck, driver, status=TripStatus.en_route,
                scheduled_start=datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc))
    await run(db, now=MORNING)
    assert await _messages(db, driver, "loading_reminder") == []


async def test_a_missing_cmr_is_asked_for_after_delivery(db):
    org, truck, driver = await _fleet(db)
    late = await _trip(db, org, truck, driver, status=TripStatus.delivered,
                       delivered_at=EVENING - timedelta(hours=3))
    await _trip(db, org, truck, driver, status=TripStatus.delivered,
                delivered_at=EVENING - timedelta(minutes=30))  # still inside the grace
    with_cmr = await _trip(db, org, truck, driver, status=TripStatus.delivered,
                           delivered_at=EVENING - timedelta(hours=3))
    db.add(TripDocument(org_id=org.id, trip_id=with_cmr.id, storage_key="k", category="CMR"))
    await db.commit()

    await run(db, now=EVENING)
    await run(db, now=EVENING + timedelta(hours=1))
    reminders = await _messages(db, driver, "cmr_reminder")
    assert len(reminders) == 1
    assert "№26" in reminders[0].body and reminders[0].dedupe_key == f"cmr:{late.id}"


async def test_service_is_warned_about_when_near_and_again_when_overdue(db):
    org, truck, driver = await _fleet(db)
    interval = ServiceInterval(truck_id=truck.id, service_type=ServiceType.oil_change,
                               next_service_date=date(2026, 10, 5))
    db.add(interval)
    await db.commit()

    await run(db, now=EVENING)
    await run(db, now=EVENING)
    soon = await _messages(db, driver, "maintenance_due")
    assert [m.title for m in soon] == ["🔧 Скоро замена масла"]
    assert "01A123BC" in soon[0].body and "05.10.2026" in soon[0].body

    await run(db, now=EVENING + timedelta(days=5))
    titles = sorted(m.title for m in await _messages(db, driver, "maintenance_due"))
    assert titles == ["🔧 Замена масла: просрочено", "🔧 Скоро замена масла"]


async def test_service_far_off_is_not_mentioned(db):
    org, truck, driver = await _fleet(db)
    db.add(ServiceInterval(truck_id=truck.id, service_type=ServiceType.general,
                           next_service_date=date(2026, 12, 1), next_service_mileage=150_000))
    await db.commit()
    await run(db, now=EVENING)
    assert await _messages(db, driver, "maintenance_due") == []


async def test_papers_are_warned_about_at_30_and_7_days_and_on_the_day(db):
    org, truck, driver = await _fleet(db)
    driver.license_expiry = date(2026, 10, 20)  # 19 days after 01.10
    truck.insurance_expiry = date(2026, 10, 1)  # lapses today
    await db.commit()

    await run(db, now=EVENING)
    await run(db, now=EVENING)
    titles = sorted(m.title for m in await _messages(db, driver, "document_expiry"))
    assert titles == [
        "⚠️ Водительское удостоверение: осталось 19 дн.",
        "⛔ Страховка UZ 01A123BC: срок истёк",
    ]

    await run(db, now=EVENING + timedelta(days=13))  # 6 days left: the 7-day warning
    assert len(await _messages(db, driver, "document_expiry")) == 3


def test_expiry_buckets():
    assert driver_notices._expiry_bucket(45) is None
    assert driver_notices._expiry_bucket(30) == "30"
    assert driver_notices._expiry_bucket(7) == "7"
    assert driver_notices._expiry_bucket(0) == "expired"
