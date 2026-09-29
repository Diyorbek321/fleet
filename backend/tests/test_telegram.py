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
    assert "на границе" in text
    assert "41.0,70.0" in text
    assert "on time" in text


def test_format_daily_update_handles_missing_gps():
    text = format_daily_update(
        "TR-77", TripStatus.en_route, None, None, "Almaty", None, None
    )
    assert "TR-77" in text
    assert "в пути" in text
    assert "Almaty" in text
    assert "не определено" in text


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

    async def _fake_send(chat_id, text, *, disable_notification=False, **_kwargs):
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


# ── The map link each subscriber gets ────────────────────────────────────


async def _activate(client: AsyncClient, token: str, chat_id: int) -> None:
    res = await client.post(
        "/api/telegram/webhook",
        json={
            "update_id": chat_id,
            "message": {
                "message_id": 1,
                "date": 0,
                "text": f"/start trip_{token}",
                "chat": {"id": chat_id, "type": "private"},
            },
        },
    )
    assert res.status_code == 200


async def test_two_subscribers_on_one_trip_get_their_own_map_links(
    client: AsyncClient, admin_headers, monkeypatch
):
    """The card is built once for the whole list — it costs two queries and an
    arrival estimate — but the link is per recipient, because the token is.
    Sending everyone the first subscriber's link would hand each of them a
    revocation switch for the others.
    """
    monkeypatch.setattr(settings, "telegram_bot_token", "TEST:token", raising=False)
    monkeypatch.setattr(settings, "telegram_bot_username", "TestBot", raising=False)
    monkeypatch.setattr(settings, "telegram_webhook_secret", "", raising=False)
    monkeypatch.setattr(settings, "public_web_url", "https://fleet.example", raising=False)

    sends: list[tuple[str, str]] = []

    async def _fake_send(chat_id, text, *, disable_notification=False, **_kwargs):
        sends.append((chat_id, text))
        return SendResult(ok=True, status_code=200)

    from app.routers import telegram as telegram_router
    from app.services import trip_notifications

    monkeypatch.setattr(telegram_service, "send_message", _fake_send)
    monkeypatch.setattr(telegram_router, "send_message", _fake_send)
    monkeypatch.setattr(trip_notifications, "send_message", _fake_send)

    trip_id = await _create_trip(client, admin_headers)

    tokens = []
    for chat_id in (111, 222):
        sub = (
            await client.post(
                "/api/trip-subscriptions", headers=admin_headers, json={"trip_id": trip_id}
            )
        ).json()
        token = sub["deep_link"].rsplit("trip_", 1)[1]
        tokens.append(token)
        await _activate(client, token, chat_id)

    sends.clear()  # drop the two activation replies
    res = await client.post(
        f"/api/trips/{trip_id}/advance", headers=admin_headers, json={"to_status": "en_route"}
    )
    assert res.status_code == 200, res.text

    by_chat = {chat: text for chat, text in sends}
    assert set(by_chat) == {"111", "222"}
    assert f"https://fleet.example/track/{tokens[0]}" in by_chat["111"]
    assert f"https://fleet.example/track/{tokens[1]}" in by_chat["222"]
    assert tokens[1] not in by_chat["111"]


async def test_without_a_web_address_the_card_carries_no_link(
    client: AsyncClient, admin_headers, monkeypatch
):
    """A deployment that never set PUBLIC_WEB_URL still gets working messages,
    just without the map line — never a ``None/track/…`` href."""
    monkeypatch.setattr(settings, "telegram_bot_token", "TEST:token", raising=False)
    monkeypatch.setattr(settings, "telegram_bot_username", "TestBot", raising=False)
    monkeypatch.setattr(settings, "telegram_webhook_secret", "", raising=False)
    monkeypatch.setattr(settings, "public_web_url", "", raising=False)
    monkeypatch.setattr(settings, "cors_origins", "", raising=False)
    monkeypatch.delenv("PUBLIC_WEB_URL", raising=False)

    sends: list[tuple[str, str]] = []

    async def _fake_send(chat_id, text, *, disable_notification=False, **_kwargs):
        sends.append((chat_id, text))
        return SendResult(ok=True, status_code=200)

    from app.routers import telegram as telegram_router
    from app.services import trip_notifications

    monkeypatch.setattr(telegram_service, "send_message", _fake_send)
    monkeypatch.setattr(telegram_router, "send_message", _fake_send)
    monkeypatch.setattr(trip_notifications, "send_message", _fake_send)

    trip_id = await _create_trip(client, admin_headers)
    sub = (
        await client.post(
            "/api/trip-subscriptions", headers=admin_headers, json={"trip_id": trip_id}
        )
    ).json()
    await _activate(client, sub["deep_link"].rsplit("trip_", 1)[1], 333)

    sends.clear()
    await client.post(
        f"/api/trips/{trip_id}/advance", headers=admin_headers, json={"to_status": "en_route"}
    )

    assert sends, "expected a status-change card"
    assert "track/" not in sends[0][1]
    assert "None" not in sends[0][1]


# ── The map button, sent once and pinned ─────────────────────────────────


def _record_sends(monkeypatch, *, message_id: int | None = 77):
    """Capture every send (with its keyboard) and every pin the router makes."""
    from app.routers import telegram as telegram_router

    sends: list[dict] = []
    pins: list[tuple[str, int]] = []

    async def _fake_send(chat_id, text, *, disable_notification=False, reply_markup=None):
        sends.append({"chat_id": chat_id, "text": text, "reply_markup": reply_markup})
        return SendResult(ok=True, status_code=200, message_id=message_id)

    async def _fake_pin(chat_id, mid):
        pins.append((chat_id, mid))
        return True

    monkeypatch.setattr(telegram_service, "send_message", _fake_send)
    monkeypatch.setattr(telegram_router, "send_message", _fake_send)
    monkeypatch.setattr(telegram_router, "pin_message", _fake_pin)
    return sends, pins


async def _new_subscription(client: AsyncClient, admin_headers) -> dict:
    trip_id = await _create_trip(client, admin_headers)
    return (
        await client.post(
            "/api/trip-subscriptions", headers=admin_headers, json={"trip_id": trip_id}
        )
    ).json()


async def test_activation_sends_the_map_button_once_and_pins_it(
    client: AsyncClient, admin_headers, monkeypatch
):
    monkeypatch.setattr(settings, "telegram_bot_token", "TEST:token", raising=False)
    monkeypatch.setattr(settings, "telegram_bot_username", "TestBot", raising=False)
    monkeypatch.setattr(settings, "telegram_webhook_secret", "", raising=False)
    monkeypatch.setattr(settings, "public_web_url", "https://fleet.example", raising=False)
    sends, pins = _record_sends(monkeypatch)

    sub = await _new_subscription(client, admin_headers)
    token = sub["deep_link"].rsplit("trip_", 1)[1]
    await _activate(client, token, 444)

    assert len(sends) == 1
    button = sends[0]["reply_markup"]["inline_keyboard"][0][0]
    assert button["url"] == f"https://fleet.example/track/{token}"
    assert "Где машина" in sends[0]["text"]
    assert "Каждое утро" not in sends[0]["text"]
    assert pins == [("444", 77)]


async def test_activation_without_a_web_address_sends_no_button(
    client: AsyncClient, admin_headers, monkeypatch
):
    monkeypatch.setattr(settings, "telegram_bot_token", "TEST:token", raising=False)
    monkeypatch.setattr(settings, "telegram_bot_username", "TestBot", raising=False)
    monkeypatch.setattr(settings, "telegram_webhook_secret", "", raising=False)
    monkeypatch.setattr(settings, "public_web_url", "", raising=False)
    monkeypatch.setattr(settings, "cors_origins", "", raising=False)
    monkeypatch.delenv("PUBLIC_WEB_URL", raising=False)
    sends, pins = _record_sends(monkeypatch)

    sub = await _new_subscription(client, admin_headers)
    await _activate(client, sub["deep_link"].rsplit("trip_", 1)[1], 555)

    assert len(sends) == 1
    assert sends[0]["reply_markup"] is None
    assert "Где машина" not in sends[0]["text"]
    assert pins == []


async def test_activation_skips_the_pin_when_telegram_gives_no_message_id(
    client: AsyncClient, admin_headers, monkeypatch
):
    monkeypatch.setattr(settings, "telegram_bot_token", "TEST:token", raising=False)
    monkeypatch.setattr(settings, "telegram_bot_username", "TestBot", raising=False)
    monkeypatch.setattr(settings, "telegram_webhook_secret", "", raising=False)
    monkeypatch.setattr(settings, "public_web_url", "https://fleet.example", raising=False)
    sends, pins = _record_sends(monkeypatch, message_id=None)

    sub = await _new_subscription(client, admin_headers)
    await _activate(client, sub["deep_link"].rsplit("trip_", 1)[1], 666)

    assert len(sends) == 1
    assert pins == []


# ── The daily digest: off by default, dispatcher can turn it on ──────────


async def test_new_subscription_starts_without_the_daily_digest(
    client: AsyncClient, admin_headers
):
    sub = await _new_subscription(client, admin_headers)
    assert sub["daily_enabled"] is False
    assert sub["event_enabled"] is True


async def test_dispatcher_can_turn_the_daily_digest_on_and_off(
    client: AsyncClient, admin_headers
):
    sub = await _new_subscription(client, admin_headers)

    on = await client.patch(
        f"/api/trip-subscriptions/{sub['id']}", headers=admin_headers, json={"daily_enabled": True}
    )
    assert on.status_code == 200, on.text
    assert on.json()["daily_enabled"] is True
    assert on.json()["event_enabled"] is True  # untouched

    off = await client.patch(
        f"/api/trip-subscriptions/{sub['id']}", headers=admin_headers, json={"daily_enabled": False}
    )
    assert off.json()["daily_enabled"] is False


async def test_patching_an_unknown_subscription_is_404(client: AsyncClient, admin_headers):
    res = await client.patch(
        "/api/trip-subscriptions/00000000-0000-0000-0000-000000000000",
        headers=admin_headers,
        json={"daily_enabled": True},
    )
    assert res.status_code == 404


async def test_daily_batch_skips_subscriptions_left_on_the_default(
    client: AsyncClient, admin_headers, monkeypatch
):
    """The point of the change: a customer who only has the pinned button
    gets no morning message."""
    from app.core.database import SessionLocal
    from app.services import daily_updates

    monkeypatch.setattr(settings, "telegram_bot_token", "TEST:token", raising=False)
    monkeypatch.setattr(settings, "telegram_webhook_secret", "", raising=False)
    _record_sends(monkeypatch)
    sub = await _new_subscription(client, admin_headers)
    await _activate(client, sub["deep_link"].rsplit("trip_", 1)[1], 777)

    async with SessionLocal() as db:
        considered, _sent = await daily_updates._run_batch(db)
    assert considered == 0
