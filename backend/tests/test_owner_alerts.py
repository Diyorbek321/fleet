"""Owner alerting: the chat link, the gate in front of it, and the bot commands.

The gate is the part worth testing hardest. Every watcher built on top of it
runs on a fifteen-minute scheduler tick, so a dedupe bug does not produce a
wrong message — it produces ninety-six correct ones a day, which is the same
thing as an owner who has muted the bot.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.models.organizations import Organization
from app.models.owner_alerts import (
    AlertKind,
    AlertSeverity,
    NotificationLog,
    TelegramAccount,
)
from app.services.owner_alerts import bus
from app.services.owner_alerts.bus import (
    Alert,
    notify_owner,
    prune_notification_log,
    render_alert,
    send_owner_document,
)
from app.services.owner_alerts.commands import (
    build_owner_deep_link,
    handle_owner_message,
    parse_owner_start,
)
from app.services.period_reports import report_tz
from app.services.telegram import SendResult


# ── Pure helpers (no DB) ─────────────────────────────────────────────────


def test_parse_owner_start_extracts_the_token():
    assert parse_owner_start("/start owner_abc-DEF_012") == "abc-DEF_012"


@pytest.mark.parametrize(
    "text",
    [
        "",
        "/start",
        "/start owner_",
        "/start trip_abc123",  # the cargo-owner namespace, not ours
        "/settings",
        "/start owner_" + "x" * 200,
        "/start owner_abc!def",
    ],
)
def test_parse_owner_start_rejects_everything_else(text: str):
    """A `trip_` payload reaching the owner parser would bind the wrong table."""
    assert parse_owner_start(text) is None


def test_owner_and_trip_deep_links_use_different_namespaces(monkeypatch):
    """One bot, two flows. Sharing a prefix would make the webhook guess."""
    from app.services.telegram import build_deep_link

    monkeypatch.setattr(settings, "telegram_bot_username", "FleetBot", raising=False)
    assert build_owner_deep_link("tok") == "https://t.me/FleetBot?start=owner_tok"
    assert build_deep_link("tok") == "https://t.me/FleetBot?start=trip_tok"


def test_render_alert_escapes_the_title_but_not_the_body():
    """Titles come from data (a plate, a shipper name); bodies are composed HTML.

    Apostrophes are deliberately left alone: half the Uzbek copy contains one
    ("yoqilg'i", "to'lov"), and escaping them makes the message unreadable
    anywhere the HTML is not rendered.
    """
    text = render_alert(
        Alert(
            kind=AlertKind.leakage,
            severity=AlertSeverity.warning,
            title="Truck <A&B> yoqilg'i",
            body="<b>12%</b> ortiqcha",
            dedupe_key="k",
        )
    )
    assert "Truck &lt;A&amp;B&gt; yoqilg'i" in text
    assert "<b>12%</b> ortiqcha" in text


def test_render_alert_appends_a_panel_link(monkeypatch):
    monkeypatch.setenv("PUBLIC_WEB_URL", "https://fleet.example.uz/")
    text = render_alert(
        Alert(
            kind=AlertKind.trip_status,
            severity=AlertSeverity.info,
            title="Reys",
            body="",
            dedupe_key="k",
            path="/trips/42",
        )
    )
    assert 'href="https://fleet.example.uz/trips/42"' in text


def test_render_alert_omits_the_link_when_no_web_url_is_configured(monkeypatch):
    """Better no link than an href starting with `None/`."""
    monkeypatch.setenv("PUBLIC_WEB_URL", "")
    monkeypatch.setattr(settings, "cors_origins", "", raising=False)
    text = render_alert(
        Alert(
            kind=AlertKind.trip_status,
            severity=AlertSeverity.info,
            title="Reys",
            body="",
            dedupe_key="k",
            path="/trips/42",
        )
    )
    assert "href=" not in text


@pytest.mark.parametrize(
    "start,end,hour,expected",
    [
        (22, 7, 23, True),
        (22, 7, 3, True),
        (22, 7, 12, False),
        (22, 7, 7, False),  # the window is half-open at the end
        (9, 17, 12, True),
        (9, 17, 8, False),
        (None, 7, 3, False),
        (8, 8, 8, False),  # equal bounds are "no window", not "always quiet"
    ],
)
def test_quiet_window_wraps_midnight_and_never_swallows_a_whole_day(
    start, end, hour, expected
):
    """Reading equal bounds as 24h quiet would silence an owner by typo."""
    account = TelegramAccount(quiet_from_hour=start, quiet_to_hour=end)
    assert bus._in_quiet_hours(account, hour) is expected


# ── Fixtures for the bus ─────────────────────────────────────────────────


@pytest.fixture
def captured_sends(monkeypatch) -> list[tuple[str, str]]:
    """Replace the Telegram transport and switch the feature gate on."""
    monkeypatch.setattr(settings, "telegram_bot_token", "TEST:token", raising=False)
    sends: list[tuple[str, str]] = []

    async def _fake_send(chat_id, text, *, disable_notification=False):
        sends.append((chat_id, text))
        return SendResult(ok=True, status_code=200)

    monkeypatch.setattr(bus, "send_message", _fake_send)
    return sends


async def _org_and_chat(db, **kwargs) -> tuple[uuid.UUID, TelegramAccount]:
    org = Organization(name="Alert Co")
    db.add(org)
    await db.flush()
    account = TelegramAccount(
        org_id=org.id,
        token=uuid.uuid4().hex,
        chat_id="900001",
        min_severity=kwargs.pop("min_severity", AlertSeverity.info),
        muted_kinds=kwargs.pop("muted_kinds", []),
        quiet_from_hour=kwargs.pop("quiet_from_hour", None),
        quiet_to_hour=kwargs.pop("quiet_to_hour", None),
        is_active=kwargs.pop("is_active", True),
        **kwargs,
    )
    db.add(account)
    await db.commit()
    return org.id, account


def _alert(**kwargs) -> Alert:
    base = dict(
        kind=AlertKind.leakage,
        severity=AlertSeverity.warning,
        title="Yoqilg'i anomaliyasi",
        body="TR-01 — 12%",
        dedupe_key="fuel:tr-01:2026-09-02",
    )
    base.update(kwargs)
    return Alert(**base)


def _quiet_now() -> tuple[int, int]:
    """A quiet window guaranteed to contain the current Tashkent hour."""
    hour = datetime.now(report_tz()).hour
    return hour, (hour + 1) % 24


def _awake_now() -> tuple[int, int]:
    hour = datetime.now(report_tz()).hour
    return (hour + 1) % 24, (hour + 2) % 24


# ── The gate ─────────────────────────────────────────────────────────────


async def test_an_alert_reaches_an_activated_chat(db, captured_sends):
    org_id, _ = await _org_and_chat(db)
    assert await notify_owner(db, org_id, _alert()) == 1
    assert captured_sends[0][0] == "900001"
    assert "Yoqilg'i anomaliyasi" in captured_sends[0][1]


async def test_the_same_fact_is_only_announced_once(db, captured_sends):
    """The scheduler re-evaluates every 15 minutes; the fact does not change."""
    org_id, _ = await _org_and_chat(db)
    assert await notify_owner(db, org_id, _alert()) == 1
    assert await notify_owner(db, org_id, _alert()) == 0
    assert await notify_owner(db, org_id, _alert()) == 0
    assert len(captured_sends) == 1


async def test_a_different_fact_gets_through_immediately(db, captured_sends):
    """Dedupe keys name the fact, so yesterday's overspend cannot mask today's."""
    org_id, _ = await _org_and_chat(db)
    await notify_owner(db, org_id, _alert(dedupe_key="fuel:tr-01:2026-09-02"))
    sent = await notify_owner(db, org_id, _alert(dedupe_key="fuel:tr-01:2026-09-03"))
    assert sent == 1
    assert len(captured_sends) == 2


async def test_the_same_fact_is_reannounced_once_its_ttl_expires(db, captured_sends):
    """A licence still expiring next month is worth one reminder per window."""
    org_id, _ = await _org_and_chat(db)
    await notify_owner(db, org_id, _alert(dedupe_ttl_hours=24))

    row = (await db.execute(select(NotificationLog))).scalar_one()
    row.sent_at = datetime.now(timezone.utc) - timedelta(hours=30)
    await db.commit()

    assert await notify_owner(db, org_id, _alert(dedupe_ttl_hours=24)) == 1
    # Refreshed in place — the unique constraint means there is only ever one.
    assert len((await db.execute(select(NotificationLog))).scalars().all()) == 1


async def test_a_muted_kind_is_dropped(db, captured_sends):
    org_id, _ = await _org_and_chat(db, muted_kinds=[AlertKind.leakage.value])
    assert await notify_owner(db, org_id, _alert(kind=AlertKind.leakage)) == 0
    assert (
        await notify_owner(
            db, org_id, _alert(kind=AlertKind.cash_mismatch, dedupe_key="cash:tr-01")
        )
        == 1
    )


async def test_severity_below_the_chat_minimum_is_dropped(db, captured_sends):
    org_id, _ = await _org_and_chat(db, min_severity=AlertSeverity.critical)
    assert await notify_owner(db, org_id, _alert(severity=AlertSeverity.warning)) == 0
    assert (
        await notify_owner(
            db, org_id, _alert(severity=AlertSeverity.critical, dedupe_key="k2")
        )
        == 1
    )


async def test_quiet_hours_defer_without_recording_the_fact(db, captured_sends):
    """The load-bearing case.

    Writing a dedupe row for an alert dropped at 03:00 would mean the owner
    never hears about it at all — the next tick would see the fact as already
    reported. So quiet hours must suppress the send and leave no trace.
    """
    quiet_from, quiet_to = _quiet_now()
    org_id, account = await _org_and_chat(
        db, quiet_from_hour=quiet_from, quiet_to_hour=quiet_to
    )

    assert await notify_owner(db, org_id, _alert()) == 0
    assert (await db.execute(select(NotificationLog))).scalars().all() == []

    # Morning: the window no longer covers now, and the fact is still true.
    account.quiet_from_hour, account.quiet_to_hour = _awake_now()
    await db.commit()
    assert await notify_owner(db, org_id, _alert()) == 1


async def test_a_critical_alert_ignores_quiet_hours(db, captured_sends):
    """Cash missing at 03:00 is still missing at 08:00 — but not still fixable."""
    quiet_from, quiet_to = _quiet_now()
    org_id, _ = await _org_and_chat(
        db,
        quiet_from_hour=quiet_from,
        quiet_to_hour=quiet_to,
        min_severity=AlertSeverity.info,
    )
    assert (
        await notify_owner(db, org_id, _alert(severity=AlertSeverity.critical)) == 1
    )


async def test_a_kind_everyone_muted_is_recorded_so_it_is_not_re_evaluated(
    db, captured_sends
):
    """Muted is a settled answer; quiet hours are a postponed one."""
    org_id, _ = await _org_and_chat(db, muted_kinds=[AlertKind.leakage.value])
    await notify_owner(db, org_id, _alert())
    assert len((await db.execute(select(NotificationLog))).scalars().all()) == 1


async def test_nothing_is_recorded_when_the_org_has_no_chats(db, captured_sends):
    """Otherwise every silent org accumulates dedupe rows forever."""
    org = Organization(name="No Chats")
    db.add(org)
    await db.commit()
    assert await notify_owner(db, org.id, _alert()) == 0
    assert (await db.execute(select(NotificationLog))).scalars().all() == []


async def test_an_unactivated_or_disabled_chat_is_not_written_to(db, captured_sends):
    org_id, account = await _org_and_chat(db)
    account.chat_id = None
    await db.commit()
    assert await notify_owner(db, org_id, _alert()) == 0

    account.chat_id = "900001"
    account.is_active = False
    await db.commit()
    assert await notify_owner(db, org_id, _alert()) == 0
    assert captured_sends == []


async def test_alerts_never_cross_organizations(db, captured_sends):
    org_a, _ = await _org_and_chat(db)
    org_b = Organization(name="Other Co")
    db.add(org_b)
    await db.flush()
    db.add(
        TelegramAccount(
            org_id=org_b.id, token=uuid.uuid4().hex, chat_id="900002",
            min_severity=AlertSeverity.info,
        )
    )
    await db.commit()

    await notify_owner(db, org_a, _alert())
    assert [chat for chat, _ in captured_sends] == ["900001"]


async def test_a_blocked_chat_is_deactivated_instead_of_retried_forever(
    db, monkeypatch
):
    """403 means the owner blocked the bot; retrying every tick burns quota."""
    monkeypatch.setattr(settings, "telegram_bot_token", "TEST:token", raising=False)

    async def _blocked(chat_id, text, *, disable_notification=False):
        return SendResult(ok=False, status_code=403, permanently_failed=True)

    monkeypatch.setattr(bus, "send_message", _blocked)
    org_id, account = await _org_and_chat(db)

    assert await notify_owner(db, org_id, _alert()) == 0
    await db.refresh(account)
    assert account.is_active is False
    # Nothing was delivered, so nothing may be recorded as delivered.
    assert (await db.execute(select(NotificationLog))).scalars().all() == []


async def test_a_transient_failure_leaves_the_fact_unreported(db, monkeypatch):
    """Telegram being down must not consume the alert."""
    monkeypatch.setattr(settings, "telegram_bot_token", "TEST:token", raising=False)
    attempts: list[int] = []

    async def _flaky(chat_id, text, *, disable_notification=False):
        attempts.append(1)
        if len(attempts) == 1:
            return SendResult(ok=False, status_code=0)
        return SendResult(ok=True, status_code=200)

    monkeypatch.setattr(bus, "send_message", _flaky)
    org_id, _ = await _org_and_chat(db)

    assert await notify_owner(db, org_id, _alert()) == 0
    assert await notify_owner(db, org_id, _alert()) == 1


async def test_notify_owner_never_raises(db, monkeypatch):
    """A scheduler tick must survive whatever the transport does."""
    monkeypatch.setattr(settings, "telegram_bot_token", "TEST:token", raising=False)

    async def _explode(chat_id, text, *, disable_notification=False):
        raise RuntimeError("telegram exploded")

    monkeypatch.setattr(bus, "send_message", _explode)
    org_id, _ = await _org_and_chat(db)
    assert await notify_owner(db, org_id, _alert()) == 0


async def test_nothing_is_sent_when_the_bot_is_not_configured(db, monkeypatch):
    monkeypatch.setattr(settings, "telegram_bot_token", "", raising=False)
    org_id, _ = await _org_and_chat(db)
    assert await notify_owner(db, org_id, _alert()) == 0


async def test_documents_share_the_gate(db, monkeypatch):
    monkeypatch.setattr(settings, "telegram_bot_token", "TEST:token", raising=False)
    files: list[tuple[str, bytes]] = []

    async def _fake_doc(chat_id, filename, content, caption):
        files.append((filename, content))
        return SendResult(ok=True, status_code=200)

    monkeypatch.setattr(bus, "_send_document", _fake_doc)
    org_id, _ = await _org_and_chat(db)

    sent = await send_owner_document(
        db,
        org_id,
        filename="avgust.xlsx",
        content=b"xlsx-bytes",
        caption="Avgust hisoboti",
        dedupe_key="report:month:2026-08",
    )
    assert sent == 1
    # The month closes once — a second tick must not re-send the workbook.
    assert (
        await send_owner_document(
            db,
            org_id,
            filename="avgust.xlsx",
            content=b"xlsx-bytes",
            caption="Avgust hisoboti",
            dedupe_key="report:month:2026-08",
        )
        == 0
    )
    assert len(files) == 1


async def test_prune_notification_log_drops_only_rows_past_every_ttl(db):
    org = Organization(name="Prune Co")
    db.add(org)
    await db.flush()
    db.add_all(
        [
            NotificationLog(
                org_id=org.id, dedupe_key="old", kind="leakage",
                sent_at=datetime.now(timezone.utc) - timedelta(days=60),
            ),
            NotificationLog(
                org_id=org.id, dedupe_key="new", kind="leakage",
                sent_at=datetime.now(timezone.utc),
            ),
        ]
    )
    await db.commit()

    assert await prune_notification_log(db, older_than_days=30) == 1
    remaining = (await db.execute(select(NotificationLog.dedupe_key))).scalars().all()
    assert remaining == ["new"]


# ── Bot commands ─────────────────────────────────────────────────────────


async def test_handle_owner_message_ignores_a_chat_with_no_owner_link(db):
    """Returning a reply here would hijack the cargo-owner trip conversation."""
    assert await handle_owner_message(db, "555000", "/settings") is None


async def test_stop_silences_the_chat_without_deleting_the_row(db):
    """The panel must still show that the director switched alerts off."""
    _, account = await _org_and_chat(db)
    reply = await handle_owner_message(db, "900001", "/stop")
    assert reply is not None
    await db.refresh(account)
    assert account.is_active is False


async def test_settings_reports_the_current_preferences(db):
    _, _ = await _org_and_chat(
        db,
        label="Direktor",
        min_severity=AlertSeverity.critical,
        muted_kinds=[AlertKind.trip_status.value],
        quiet_from_hour=22,
        quiet_to_hour=7,
    )
    reply = await handle_owner_message(db, "900001", "/settings")
    assert "Direktor" in reply
    assert "Reys holati" in reply
    assert "22:00" in reply


async def test_a_group_chat_command_suffix_is_stripped(db):
    """Telegram appends @botname to commands sent in groups."""
    _, account = await _org_and_chat(db)
    reply = await handle_owner_message(db, "900001", "/stop@FleetBot")
    assert reply is not None
    await db.refresh(account)
    assert account.is_active is False


async def test_unknown_text_falls_back_to_the_command_list(db):
    _, _ = await _org_and_chat(db)
    reply = await handle_owner_message(db, "900001", "salom")
    assert "/settings" in reply


# ── Admin API ────────────────────────────────────────────────────────────


async def _link(client: AsyncClient, headers, **body) -> dict:
    res = await client.post("/api/org/telegram/link", headers=headers, json=body)
    assert res.status_code == 201, res.text
    return res.json()


async def test_link_returns_a_token_and_deep_link(
    client: AsyncClient, admin_headers, monkeypatch
):
    monkeypatch.setattr(settings, "telegram_bot_username", "FleetBot", raising=False)
    body = await _link(client, admin_headers, label="Direktor")
    assert body["label"] == "Direktor"
    assert body["deep_link"] == f"https://t.me/FleetBot?start=owner_{body['token']}"


async def test_listing_never_exposes_a_chat_id(client: AsyncClient, admin_headers, db):
    """The chat id is the one thing an admin must not be able to read: with it,
    anyone inside the customer could point alerts at a chat of their choosing."""
    await _link(client, admin_headers, label="Direktor")
    account = (await db.execute(select(TelegramAccount))).scalar_one()
    account.chat_id = "777"
    account.activated_at = datetime.now(timezone.utc)
    await db.commit()

    res = await client.get("/api/org/telegram", headers=admin_headers)
    assert res.status_code == 200, res.text
    row = res.json()[0]
    assert "chat_id" not in row
    assert "777" not in res.text
    assert row["activated"] is True
    # The token has done its job; echoing it back leaves a live re-binding
    # credential in every list response.
    assert row["deep_link"] is None


async def test_a_new_chat_defaults_to_the_conservative_setting(
    client: AsyncClient, admin_headers
):
    """Defaulting to "everything, at any hour" is how an owner mutes the bot."""
    await _link(client, admin_headers)
    row = (await client.get("/api/org/telegram", headers=admin_headers)).json()[0]
    assert row["min_severity"] == "warning"
    assert row["muted_kinds"] == []
    assert row["quiet_from_hour"] == 22
    assert row["quiet_to_hour"] == 7


async def test_patch_updates_preferences(client: AsyncClient, admin_headers):
    created = await _link(client, admin_headers)
    res = await client.patch(
        f"/api/org/telegram/{created['id']}",
        headers=admin_headers,
        json={
            "muted_kinds": ["trip_status", "briefing"],
            "min_severity": "critical",
            "quiet_from_hour": 23,
        },
    )
    assert res.status_code == 200, res.text
    row = res.json()
    assert row["muted_kinds"] == ["trip_status", "briefing"]
    assert row["min_severity"] == "critical"
    assert row["quiet_from_hour"] == 23


async def test_patch_can_clear_the_quiet_window(client: AsyncClient, admin_headers):
    """Explicit null must mean "no window", not "leave it alone" — otherwise an
    owner who wants alerts at any hour has to unlink and start over."""
    created = await _link(client, admin_headers)
    res = await client.patch(
        f"/api/org/telegram/{created['id']}",
        headers=admin_headers,
        json={"quiet_from_hour": None, "quiet_to_hour": None},
    )
    assert res.status_code == 200, res.text
    assert res.json()["quiet_from_hour"] is None
    assert res.json()["quiet_to_hour"] is None


async def test_patch_rejects_an_hour_outside_the_clock(
    client: AsyncClient, admin_headers
):
    created = await _link(client, admin_headers)
    res = await client.patch(
        f"/api/org/telegram/{created['id']}",
        headers=admin_headers,
        json={"quiet_from_hour": 25},
    )
    assert res.status_code == 422


async def test_delete_unlinks_the_chat(client: AsyncClient, admin_headers):
    created = await _link(client, admin_headers)
    res = await client.delete(f"/api/org/telegram/{created['id']}", headers=admin_headers)
    assert res.status_code == 204
    assert (await client.get("/api/org/telegram", headers=admin_headers)).json() == []


async def test_an_operator_cannot_mint_or_change_links(
    client: AsyncClient, admin_headers, operator_headers
):
    created = await _link(client, admin_headers)
    assert (
        await client.post("/api/org/telegram/link", headers=operator_headers, json={})
    ).status_code == 403
    assert (
        await client.patch(
            f"/api/org/telegram/{created['id']}",
            headers=operator_headers,
            json={"is_active": False},
        )
    ).status_code == 403
    assert (
        await client.delete(
            f"/api/org/telegram/{created['id']}", headers=operator_headers
        )
    ).status_code == 403


async def test_another_orgs_chat_is_invisible(client: AsyncClient, admin_headers, db):
    """Chat ids are opaque, but the row id is a plain UUID an admin can guess at."""
    other = Organization(name="Rival Co")
    db.add(other)
    await db.flush()
    account = TelegramAccount(org_id=other.id, token=uuid.uuid4().hex, label="Rival")
    db.add(account)
    await db.commit()

    assert (await client.get("/api/org/telegram", headers=admin_headers)).json() == []
    res = await client.patch(
        f"/api/org/telegram/{account.id}", headers=admin_headers, json={"is_active": False}
    )
    assert res.status_code == 404


async def test_the_test_message_needs_an_activated_chat(
    client: AsyncClient, admin_headers, db, monkeypatch
):
    created = await _link(client, admin_headers)
    res = await client.post(f"/api/org/telegram/{created['id']}/test", headers=admin_headers)
    assert res.status_code == 400

    from app.routers import owner_alerts as owner_router

    monkeypatch.setattr(settings, "telegram_bot_token", "TEST:token", raising=False)
    sends: list[str] = []

    async def _fake_send(chat_id, text, *, disable_notification=False):
        sends.append(chat_id)
        return SendResult(ok=True, status_code=200)

    monkeypatch.setattr(owner_router, "send_message", _fake_send)

    account = (await db.execute(select(TelegramAccount))).scalar_one()
    account.chat_id = "42"
    await db.commit()

    res = await client.post(f"/api/org/telegram/{created['id']}/test", headers=admin_headers)
    assert res.status_code == 200, res.text
    assert res.json() == {"sent": True}
    assert sends == ["42"]


async def test_a_test_message_bypasses_mute_and_quiet_hours(
    client: AsyncClient, admin_headers, db, monkeypatch
):
    """"Did my link work?" must not be answerable with silence."""
    created = await _link(client, admin_headers)
    await client.patch(
        f"/api/org/telegram/{created['id']}",
        headers=admin_headers,
        json={"min_severity": "critical", "muted_kinds": [k.value for k in AlertKind]},
    )

    from app.routers import owner_alerts as owner_router

    monkeypatch.setattr(settings, "telegram_bot_token", "TEST:token", raising=False)
    sends: list[str] = []

    async def _fake_send(chat_id, text, *, disable_notification=False):
        sends.append(chat_id)
        return SendResult(ok=True, status_code=200)

    monkeypatch.setattr(owner_router, "send_message", _fake_send)

    account = (await db.execute(select(TelegramAccount))).scalar_one()
    account.chat_id = "43"
    await db.commit()

    res = await client.post(f"/api/org/telegram/{created['id']}/test", headers=admin_headers)
    assert res.json() == {"sent": True}
    assert sends == ["43"]


# ── Webhook activation ───────────────────────────────────────────────────


async def _post_update(client: AsyncClient, text: str, chat_id: int = 5150):
    return await client.post(
        "/api/telegram/webhook",
        json={
            "update_id": 1,
            "message": {
                "message_id": 1,
                "date": 0,
                "text": text,
                "chat": {"id": chat_id, "type": "private", "username": "director"},
            },
        },
    )


async def test_the_webhook_activates_an_owner_chat(
    client: AsyncClient, admin_headers, db, monkeypatch
):
    """The full link flow: only the token ever leaves the server."""
    monkeypatch.setattr(settings, "telegram_bot_token", "TEST:token", raising=False)
    monkeypatch.setattr(settings, "telegram_webhook_secret", "", raising=False)

    from app.routers import telegram as telegram_router

    sends: list[tuple[str, str]] = []

    async def _fake_send(chat_id, text, *, disable_notification=False):
        sends.append((chat_id, text))
        return SendResult(ok=True, status_code=200)

    monkeypatch.setattr(telegram_router, "send_message", _fake_send)

    created = await _link(client, admin_headers, label=None)
    res = await _post_update(client, f"/start owner_{created['token']}")
    assert res.status_code == 200
    assert sends and sends[0][0] == "5150"

    row = (await client.get("/api/org/telegram", headers=admin_headers)).json()[0]
    assert row["activated"] is True
    assert row["activated_at"] is not None


async def test_a_bad_owner_token_is_answered_not_ignored(
    client: AsyncClient, monkeypatch
):
    monkeypatch.setattr(settings, "telegram_bot_token", "TEST:token", raising=False)
    monkeypatch.setattr(settings, "telegram_webhook_secret", "", raising=False)

    from app.routers import telegram as telegram_router

    sends: list[tuple[str, str]] = []

    async def _fake_send(chat_id, text, *, disable_notification=False):
        sends.append((chat_id, text))
        return SendResult(ok=True, status_code=200)

    monkeypatch.setattr(telegram_router, "send_message", _fake_send)

    assert (await _post_update(client, "/start owner_deadbeef")).status_code == 200
    assert "❌" in sends[0][1]


async def test_an_owner_chat_answers_its_own_commands(
    client: AsyncClient, admin_headers, db, monkeypatch
):
    monkeypatch.setattr(settings, "telegram_bot_token", "TEST:token", raising=False)
    monkeypatch.setattr(settings, "telegram_webhook_secret", "", raising=False)

    from app.routers import telegram as telegram_router

    sends: list[tuple[str, str]] = []

    async def _fake_send(chat_id, text, *, disable_notification=False):
        sends.append((chat_id, text))
        return SendResult(ok=True, status_code=200)

    monkeypatch.setattr(telegram_router, "send_message", _fake_send)

    created = await _link(client, admin_headers)
    await _post_update(client, f"/start owner_{created['token']}")
    sends.clear()

    await _post_update(client, "/settings")
    assert "Sozlamalar" in sends[0][1]

    await _post_update(client, "/stop")
    row = (await client.get("/api/org/telegram", headers=admin_headers)).json()[0]
    assert row["is_active"] is False
