"""The panel's bell: every owner alert, once, for the company it belongs to.

What matters: the bell fills even when no Telegram chat is linked (that is the
whole reason it exists), a fact restated every tick is one entry, and one
company never sees another's alerts.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.core.config import settings
from app.models.organizations import Organization
from app.models.panel_notifications import PanelNotification
from app.models.users import User
from app.services.owner_alerts import Alert, AlertKind, AlertSeverity, notify_owner
from app.services.panel_notifications import plain_text


def _alert(key: str = "trip_delay:1:warning", **over) -> Alert:
    fields = dict(
        kind=AlertKind.trip_delay,
        severity=AlertSeverity.warning,
        title="01A123BC - Anvar - TR-1 — опоздание 6 ч",
        body="План: <b>29.09 10:00</b>\nНаправление: <b>Toshkent → Moskva</b>",
        dedupe_key=key,
        path="/trips/abc",
    )
    fields.update(over)
    return Alert(**fields)


async def _org(db, name: str = "Bell Co") -> Organization:
    org = Organization(name=name)
    db.add(org)
    await db.commit()
    return org


async def _count(db, org_id) -> int:
    return (
        await db.execute(
            select(func.count()).select_from(PanelNotification).where(PanelNotification.org_id == org_id)
        )
    ).scalar_one()


def test_the_bell_shows_text_not_telegram_markup():
    assert plain_text("План: <b>29.09</b>\nИ &amp; всё") == "План: 29.09\nИ & всё"


async def test_an_alert_reaches_the_bell_without_any_telegram_chat(db, monkeypatch):
    monkeypatch.setattr(settings, "telegram_bot_token", "", raising=False)
    org = await _org(db)

    await notify_owner(db, org.id, _alert())
    await notify_owner(db, org.id, _alert())  # the next tick restates the fact

    row = (
        await db.execute(select(PanelNotification).where(PanelNotification.org_id == org.id))
    ).scalar_one()
    assert row.kind == "trip_delay"
    assert row.severity == "warning"
    assert row.path == "/trips/abc"
    assert "<b>" not in row.body and "Toshkent → Moskva" in row.body


async def test_the_telegram_overflow_summary_stays_out_of_the_bell(db):
    org = await _org(db)
    await notify_owner(db, org.id, _alert(key="trip_delay:overflow:2026-09-29"))
    assert await _count(db, org.id) == 0


# ── API ──────────────────────────────────────────────────────────────────


async def _admin_org_id(db) -> uuid.UUID:
    return (await db.execute(select(User.org_id).where(User.email == "admin@test.com"))).scalar_one()


async def test_unread_counts_what_arrived_since_the_bell_was_opened(
    client: AsyncClient, admin_headers, db
):
    org_id = await _admin_org_id(db)
    await notify_owner(db, org_id, _alert(key="a"))
    await notify_owner(db, org_id, _alert(key="b", title="Second"))

    feed = (await client.get("/api/notifications", headers=admin_headers)).json()
    assert feed["unread_count"] == 2
    assert [n["title"] for n in feed["items"]][0] == "Second"

    seen = (await client.post("/api/notifications/seen", headers=admin_headers)).json()
    assert seen["unread_count"] == 0
    assert len(seen["items"]) == 2  # read, not gone

    await notify_owner(db, org_id, _alert(key="c"))
    assert (await client.get("/api/notifications", headers=admin_headers)).json()["unread_count"] == 1


async def test_a_new_account_does_not_inherit_the_companys_backlog(
    client: AsyncClient, admin_headers, db
):
    org_id = await _admin_org_id(db)
    old = PanelNotification(
        org_id=org_id,
        kind="leakage",
        severity="warning",
        title="Old",
        body="",
        dedupe_key="old",
        created_at=datetime.now(timezone.utc) - timedelta(days=2),
    )
    db.add(old)
    await db.commit()

    feed = (await client.get("/api/notifications", headers=admin_headers)).json()
    assert feed["unread_count"] == 0
    assert [n["title"] for n in feed["items"]] == ["Old"]


async def test_another_companys_alerts_are_invisible(client: AsyncClient, admin_headers, db):
    other = await _org(db, name="Other Co")
    await notify_owner(db, other.id, _alert(key="theirs"))

    feed = (await client.get("/api/notifications", headers=admin_headers)).json()
    assert feed["items"] == []
    assert feed["unread_count"] == 0


@pytest.mark.parametrize("method,path", [("get", "/api/notifications"), ("post", "/api/notifications/seen")])
async def test_drivers_have_no_bell(client: AsyncClient, driver_login, method, path):
    res = await getattr(client, method)(path, headers=driver_login["headers"])
    assert res.status_code == 403
