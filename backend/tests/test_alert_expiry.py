"""Muddat eslatmasi: what the expiry watcher says, and — mostly — what it does not.

Escalation is the easy half. The half that decides whether this feature survives
contact with a customer is the silence between messages: the job re-evaluates
every tick, and a licence that is still expiring next month is still expiring
next month. Get the dedupe wrong and the owner receives the same correct
sentence dozens of times, which is indistinguishable from a bug and ends with
the bot muted.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models.drivers import Driver
from app.models.enums import DriverStatus, ServiceStatus, ServiceType
from app.models.maintenance import ServiceInterval
from app.models.organizations import Organization
from app.models.owner_alerts import AlertKind, AlertSeverity, NotificationLog, TelegramAccount
from app.models.trucks import Truck
from app.services.owner_alerts import bus, expiry
from app.services.owner_alerts.expiry import dedupe_ttl_hours, run, severity_for
from app.services.telegram import SendResult


# ── Buckets (no DB) ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "days_left,already_late,expected",
    [
        (30, False, AlertSeverity.info),
        (8, False, AlertSeverity.info),
        (7, False, AlertSeverity.warning),
        (1, False, AlertSeverity.warning),
        (0, False, AlertSeverity.warning),   # valid today, illegal tomorrow
        (-1, False, AlertSeverity.critical),
        (-400, False, AlertSeverity.critical),
    ],
)
def test_severity_escalates_as_the_date_approaches(days_left, already_late, expected):
    """One level for everything would either page an owner about paperwork a
    month out or bury a truck that cannot legally leave the yard today."""
    assert severity_for(days_left, already_late=already_late) is expected


def test_a_service_overdue_on_mileage_is_critical_despite_a_future_date():
    """An interval trips on km or on days, whichever comes first. Reading only
    the date would report a truck 3 000 km past its oil change as "info"."""
    assert severity_for(20, already_late=True) is AlertSeverity.critical
    assert severity_for(None, already_late=True) is AlertSeverity.critical


def test_the_dedupe_key_carries_the_bucket_so_one_licence_speaks_three_times():
    """Without the bucket in the key the first message wins and the escalation
    never happens: the owner hears "30 kun qoldi" and nothing after that."""
    row = {"driver_id": "d-1", "driver_name": "Vali", "license_number": "AA1"}
    keys = {
        expiry._licence_alert(
            {**row, "days_left": d}, severity_for(d, already_late=d < 0)
        ).dedupe_key
        for d in (25, 3, -2)
    }
    assert len(keys) == 3


def test_each_buckets_ttl_outlasts_the_bucket_it_belongs_to():
    """A TTL shorter than its bucket is wide restates the same fact daily.

    ``info`` spans days 30..8 (23 days) and ``warning`` spans days 7..0, so both
    TTLs have to clear those windows for "once per bucket" to hold.
    """
    assert dedupe_ttl_hours(AlertSeverity.info) > 23 * 24
    assert dedupe_ttl_hours(AlertSeverity.warning) > 7 * 24


def test_an_expired_document_nags_weekly_rather_than_daily_or_never():
    """Critical is the one bucket a document never leaves, so its key would be
    permanent. Left alone the owner is told once; at a 24h TTL they are told
    every day until they mute the bot."""
    ttl = dedupe_ttl_hours(AlertSeverity.critical)
    assert 6 * 24 <= ttl <= 8 * 24


def test_an_expired_licence_message_says_how_long_ago_and_why_it_matters():
    alert = expiry._licence_alert(
        {
            "driver_id": "d-1",
            "driver_name": "Vali Aliyev",
            "license_number": "AA1234567",
            "license_expiry": "2026-08-01",
            "days_left": -12,
        },
        AlertSeverity.critical,
    )
    assert "tugagan" in alert.title
    assert "12 kun" in alert.body
    assert alert.path == "/drivers/d-1"
    assert alert.kind is AlertKind.document_expiry


def test_a_drivers_name_cannot_smuggle_markup_into_the_body():
    """Titles are escaped by the bus; body lines are not, so this module owns
    the escaping of every value it interpolates into one."""
    alert = expiry._service_alert(
        {
            "truck_id": "t-1",
            "truck_name": "<b>hack</b>",
            "plate_number": "01A123BC",
            "service_type": "oil_change",
            "next_service_date": "2026-09-10",
            "days_left": 5,
        },
        AlertSeverity.warning,
    )
    assert "&lt;b&gt;hack&lt;/b&gt;" in alert.body
    assert "Moy almashtirish" in alert.body
    assert alert.kind is AlertKind.maintenance_overdue


def test_the_batch_is_ordered_most_urgent_first():
    """The per-run cap only protects the owner if what survives it is the part
    that cannot wait for the next tick."""
    data = {
        "license_expiries": [
            {"driver_id": "far", "driver_name": "A", "days_left": 29},
            {"driver_id": "gone", "driver_name": "B", "days_left": -3, "expired": True},
            {"driver_id": "soon", "driver_name": "C", "days_left": 2},
        ],
        "service_due": [],
    }
    order = [item.alert.dedupe_key for item in expiry._collect(data, set())]
    assert order[0].startswith("expiry:licence:gone")
    assert order[1].startswith("expiry:licence:soon")
    assert order[2].startswith("expiry:licence:far")


# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture
def captured(monkeypatch) -> list[tuple[str, str]]:
    """Replace the Telegram transport and switch the feature gate on."""
    monkeypatch.setattr(settings, "telegram_bot_token", "TEST:token", raising=False)
    sends: list[tuple[str, str]] = []

    async def _fake_send(chat_id, text, *, disable_notification=False):
        sends.append((chat_id, text))
        return SendResult(ok=True, status_code=200)

    monkeypatch.setattr(bus, "send_message", _fake_send)
    return sends


async def _org_with_chat(
    db, *, name: str = "Alert Co", org_active: bool = True, chat_id: str = "900001"
):
    org = Organization(name=name, is_active=org_active)
    db.add(org)
    await db.flush()
    db.add(
        TelegramAccount(
            org_id=org.id,
            token=uuid.uuid4().hex,
            chat_id=chat_id,
            min_severity=AlertSeverity.info,
            muted_kinds=[],
            # No quiet window: this suite is about escalation and dedupe, and a
            # default 22→07 window would make every assertion depend on the
            # wall-clock hour the CI runner happened to start at.
            quiet_from_hour=None,
            quiet_to_hour=None,
        )
    )
    await db.commit()
    return org.id


async def _driver(
    db,
    org_id,
    *,
    days: int,
    status: DriverStatus = DriverStatus.active,
    name: str = "Vali",
):
    driver = Driver(
        org_id=org_id,
        name=name,
        license_number=f"LIC-{uuid.uuid4().hex[:10]}",
        license_expiry=date.today() + timedelta(days=days),
        status=status,
    )
    db.add(driver)
    await db.commit()
    return driver


async def _interval(
    db, org_id, *, days: int | None, status: ServiceStatus = ServiceStatus.scheduled
):
    truck = Truck(org_id=org_id, name="Kamaz", plate_number=f"01A{uuid.uuid4().hex[:5].upper()}")
    db.add(truck)
    await db.flush()
    db.add(
        ServiceInterval(
            truck_id=truck.id,
            service_type=ServiceType.oil_change,
            next_service_date=date.today() + timedelta(days=days) if days is not None else None,
            status=status,
        )
    )
    await db.commit()
    return truck


# ── The watcher end to end ───────────────────────────────────────────────


async def test_an_expiring_licence_reaches_the_owner(db, captured):
    org_id = await _org_with_chat(db)
    await _driver(db, org_id, days=20, name="Vali Aliyev")

    assert await run(db) == 1
    chat_id, text = captured[0]
    assert chat_id == "900001"
    assert "Vali Aliyev" in text
    assert "20 kun" in text


async def test_the_same_licence_is_not_repeated_on_the_next_tick(db, captured):
    """The scheduler re-runs this hourly; the licence's date does not move."""
    org_id = await _org_with_chat(db)
    await _driver(db, org_id, days=20)

    assert await run(db) == 1
    assert await run(db) == 0
    assert await run(db) == 0
    assert len(captured) == 1


async def test_a_licence_crossing_into_the_next_bucket_is_announced_again(db, captured):
    """The whole point of bucketing: the owner hears about it as it gets closer,
    not once when it first appears on the horizon."""
    org_id = await _org_with_chat(db)
    driver = await _driver(db, org_id, days=20)
    assert await run(db) == 1

    driver.license_expiry = date.today() + timedelta(days=3)
    await db.commit()
    assert await run(db) == 1

    driver.license_expiry = date.today() - timedelta(days=1)
    await db.commit()
    assert await run(db) == 1

    assert len(captured) == 3
    assert "tugagan" in captured[2][1]


async def test_an_overdue_service_interval_arrives_as_critical(db, captured):
    org_id = await _org_with_chat(db)
    await _interval(db, org_id, days=None, status=ServiceStatus.overdue)

    assert await run(db) == 1
    assert "🚨" in captured[0][1]
    assert "probeg" in captured[0][1]

    kinds = (await db.execute(select(NotificationLog.kind))).scalars().all()
    assert kinds == [AlertKind.maintenance_overdue.value]


async def test_a_past_service_date_is_critical_even_before_the_status_job_runs(db, captured):
    """``refresh_service_statuses`` flips the status, but it is a separate job on
    a separate tick. Reading only ``status`` would report a service two weeks
    past its date as a gentle "yaqinlashdi"."""
    org_id = await _org_with_chat(db)
    await _interval(db, org_id, days=-14, status=ServiceStatus.scheduled)

    assert await run(db) == 1
    assert "o'tgan" in captured[0][1]


async def test_a_document_beyond_the_horizon_stays_silent(db, captured):
    org_id = await _org_with_chat(db)
    await _driver(db, org_id, days=90)
    await _interval(db, org_id, days=90)

    assert await run(db) == 0
    assert captured == []


async def test_an_inactive_drivers_expired_licence_is_never_announced(db, captured):
    """Nobody renews the licence of a driver who left, and critical re-fires
    weekly — so this one row would become a permanent recurring message."""
    org_id = await _org_with_chat(db)
    await _driver(db, org_id, days=-30, status=DriverStatus.inactive, name="Ketgan")
    await _driver(db, org_id, days=-30, status=DriverStatus.on_leave, name="Ta'tilda")

    assert await run(db) == 1
    assert "Ta'tilda" in captured[0][1]


async def test_alerts_never_cross_organizations(db, captured):
    """One customer being told about another customer's trucks is the worst
    failure this codebase has; the reminder query is org-scoped and stays so."""
    org_a = await _org_with_chat(db, name="A Co", chat_id="111")
    org_b = await _org_with_chat(db, name="B Co", chat_id="222")
    await _driver(db, org_a, days=5, name="A haydovchi")
    await _driver(db, org_b, days=5, name="B haydovchi")

    assert await run(db) == 2
    by_chat = {chat: text for chat, text in captured}
    assert "A haydovchi" in by_chat["111"] and "B haydovchi" not in by_chat["111"]
    assert "B haydovchi" in by_chat["222"] and "A haydovchi" not in by_chat["222"]


async def test_an_org_with_no_linked_chat_is_left_alone(db, captured):
    """Nothing to send and — critically — nothing recorded, so the alert is
    still waiting the day the owner finally links a chat."""
    org = Organization(name="No Telegram")
    db.add(org)
    await db.flush()
    await _driver(db, org.id, days=2)
    await db.commit()

    assert await run(db) == 0
    assert (await db.execute(select(NotificationLog))).scalars().all() == []


async def test_a_suspended_organization_is_not_messaged(db, captured):
    org_id = await _org_with_chat(db, org_active=False)
    await _driver(db, org_id, days=2)

    assert await run(db) == 0
    assert captured == []


async def test_a_backlog_is_spread_across_ticks_urgent_first(db, captured):
    """A fleet linking its chat for the first time has years of lapsed paperwork
    behind it. Delivering all of it at once is how the bot gets muted on day one.
    """
    org_id = await _org_with_chat(db)
    for i in range(3):
        await _driver(db, org_id, days=-10, name=f"Muddati o'tgan {i}")
    for i in range(14):
        await _driver(db, org_id, days=25, name=f"Uzoq {i}")

    first = await run(db)
    assert first == expiry._MAX_ALERTS_PER_ORG_PER_RUN
    assert sum("Muddati o'tgan" in text for _, text in captured) == 3

    second = await run(db)
    assert first + second == 17
    assert await run(db) == 0


async def test_run_survives_an_organization_it_cannot_evaluate(db, captured, monkeypatch):
    """A scheduler tick that dies on one tenant costs every other tenant its
    alerts for that tick."""
    org_id = await _org_with_chat(db)
    await _driver(db, org_id, days=2)

    async def _explode(*args, **kwargs):
        raise RuntimeError("reminder query blew up")

    monkeypatch.setattr(expiry, "upcoming_expiries", _explode)
    assert await run(db) == 0
    assert captured == []


async def test_a_licence_is_reannounced_once_its_weekly_window_lapses(db, captured):
    """The expired bucket is a standing reminder, not a one-off: it has to come
    back next week and keep coming back until the document is renewed."""
    org_id = await _org_with_chat(db)
    await _driver(db, org_id, days=-3)
    assert await run(db) == 1

    row = (await db.execute(select(NotificationLog))).scalar_one()
    row.sent_at = datetime.now(timezone.utc) - timedelta(days=8)
    await db.commit()

    assert await run(db) == 1
    assert len(captured) == 2
