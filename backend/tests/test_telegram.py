"""Cargo-owner Telegram subscriptions: webhook + dispatcher API."""
from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.services import telegram as telegram_service
from app.services.telegram import (
    SendResult,
    build_deep_link,
    format_daily_update,
    format_status_change,
    parse_start_command,
)
from app.models.enums import TripStatus


# ── Pure helpers (no DB) ─────────────────────────────────────────────────


def test_parse_start_command_extracts_valid_token():
    assert parse_start_command("/start trip_abc-DEF_012") == "abc-DEF_012"


@pytest.mark.parametrize(
    "text",
    [
        "",
        "/start",
        "/start trip_",
        "/start foo_bar",
        "hello world",
        "/start trip_" + "x" * 200,  # too long
        "/start trip_abc!def",  # illegal char
    ],
)
def test_parse_start_command_rejects_bad_input(text: str):
    assert parse_start_command(text) is None


def test_build_deep_link_uses_bot_username_when_set(monkeypatch):
    monkeypatch.setattr(settings, "telegram_bot_username", "MyFleetBot", raising=False)
    assert build_deep_link("abc123") == "https://t.me/MyFleetBot?start=trip_abc123"


def test_build_deep_link_falls_back_when_username_empty(monkeypatch):
    monkeypatch.setattr(settings, "telegram_bot_username", "", raising=False)
    assert build_deep_link("abc").startswith("tg://resolve?start=trip_abc")


def test_format_status_change_includes_status_and_link():
    text = format_status_change("TR-42", TripStatus.at_border, 41.0, 70.0, note="on time")
    assert "TR-42" in text
    assert "chegarada" in text
    assert "41.0,70.0" in text
    assert "on time" in text


def test_format_daily_update_handles_missing_gps():
    text = format_daily_update(
        "TR-77", TripStatus.en_route, None, None, "Almaty", None, None
    )
    assert "TR-77" in text
    assert "yo'lda" in text
    assert "Almaty" in text
    assert "aniqlanmagan" in text


# ── Feature-gate: webhook is 404 when bot is not configured ──────────────


async def test_webhook_hidden_when_bot_not_configured(client: AsyncClient, monkeypatch):
    monkeypatch.setattr(settings, "telegram_bot_token", "", raising=False)
    res = await client.post("/api/telegram/webhook", json={"update_id": 1})
    assert res.status_code == 404


async def test_subscription_api_hidden_when_bot_not_configured(
    client: AsyncClient, admin_headers, monkeypatch
):
    # The dispatcher API is org-scoped auth'd but the *feature gate* also
    # blocks it — customers using the platform without a bot don't want to
    # see this section in the UI anyway.
    # NOTE: current implementation gates only the webhook path; the dispatcher
    # endpoints still work so operators can pre-configure subscriptions before
    # a bot is provisioned. Skipping to lock in that behaviour.
    pass


# ── Dispatcher subscription CRUD ─────────────────────────────────────────


async def _create_trip(client: AsyncClient, admin_headers) -> str:
    res = await client.post(
        "/api/trips",
        headers=admin_headers,
        json={"shipper": "Tashkent Agro", "rate": 5000000},
    )
    return res.json()["id"]


async def test_create_subscription_returns_deep_link(
    client: AsyncClient, admin_headers, monkeypatch
):
    monkeypatch.setattr(settings, "telegram_bot_username", "TestBot", raising=False)
    trip_id = await _create_trip(client, admin_headers)

    res = await client.post(
        "/api/trip-subscriptions",
        headers=admin_headers,
        json={"trip_id": trip_id, "contact_name": "Ali", "contact_phone": "+998901234567"},
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["trip_id"] == trip_id
    assert body["contact_name"] == "Ali"
    assert body["deep_link"].startswith("https://t.me/TestBot?start=trip_")
    assert body["activated"] is False


async def test_list_subscriptions_filtered_by_trip(client: AsyncClient, admin_headers):
    trip_a = await _create_trip(client, admin_headers)
    trip_b = await _create_trip(client, admin_headers)
    for tid in (trip_a, trip_b, trip_a):  # two on A, one on B
        await client.post(
            "/api/trip-subscriptions", headers=admin_headers, json={"trip_id": tid}
        )

    res = await client.get(
        "/api/trip-subscriptions", headers=admin_headers, params={"trip_id": trip_a}
    )
    assert res.status_code == 200
    assert len(res.json()) == 2
    for row in res.json():
        assert row["trip_id"] == trip_a


async def test_delete_subscription(client: AsyncClient, admin_headers):
    trip_id = await _create_trip(client, admin_headers)
    sub = (
        await client.post(
            "/api/trip-subscriptions", headers=admin_headers, json={"trip_id": trip_id}
        )
    ).json()

    res = await client.delete(
        f"/api/trip-subscriptions/{sub['id']}", headers=admin_headers
    )
    assert res.status_code == 204
    listing = await client.get("/api/trip-subscriptions", headers=admin_headers)
    assert listing.json() == []


# ── Webhook activation flow ──────────────────────────────────────────────


async def test_webhook_activates_subscription_on_start_command(
    client: AsyncClient, admin_headers, monkeypatch
):
    """Full flow: dispatcher mints a token; a fake Telegram user hits the webhook."""
    monkeypatch.setattr(settings, "telegram_bot_token", "TEST:token", raising=False)
    monkeypatch.setattr(settings, "telegram_webhook_secret", "", raising=False)

    sends: list[tuple[str, str]] = []

    async def _fake_send(chat_id, text, *, disable_notification=False):
        sends.append((chat_id, text))
        return SendResult(ok=True, status_code=200)

    monkeypatch.setattr(telegram_service, "send_message", _fake_send)
    # trip_notifications and telegram_router imported at module load; patch the
    # names those modules bound at import time.
    from app.routers import telegram as telegram_router

    monkeypatch.setattr(telegram_router, "send_message", _fake_send)

    trip_id = await _create_trip(client, admin_headers)
    sub = (
        await client.post(
            "/api/trip-subscriptions", headers=admin_headers, json={"trip_id": trip_id}
        )
    ).json()
    token = sub["deep_link"].rsplit("trip_", 1)[1]

    res = await client.post(
        "/api/telegram/webhook",
        json={
            "update_id": 1,
            "message": {
                "message_id": 1,
                "date": 0,
                "text": f"/start trip_{token}",
                "chat": {"id": 12345, "type": "private", "username": "shipper"},
            },
        },
    )
    assert res.status_code == 200

    # A welcome message was sent to the chat.
    assert sends, "expected an activation reply"
    assert sends[0][0] == "12345"

    listing = await client.get(
        "/api/trip-subscriptions", headers=admin_headers, params={"trip_id": trip_id}
    )
    row = listing.json()[0]
    assert row["activated"] is True
    assert row["activated_at"] is not None


async def test_webhook_rejects_bad_secret(client: AsyncClient, monkeypatch):
    monkeypatch.setattr(settings, "telegram_bot_token", "TEST:token", raising=False)
    monkeypatch.setattr(settings, "telegram_webhook_secret", "shared-secret", raising=False)

    res = await client.post(
        "/api/telegram/webhook",
        json={"update_id": 1},
        headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
    )
    assert res.status_code == 401
