"""Telegram Bot API client + message templating.

Thin wrapper around the Bot HTTP API (``httpx`` — already a dep, so no extra
``python-telegram-bot`` / ``aiogram`` dependency creep). Exposes:

* :func:`send_message` — resilient sendMessage that never raises into a
  scheduler tick; it logs and returns a boolean so batch pushes can keep
  going when one chat fails (blocked bot, deleted chat, etc.).
* :func:`build_deep_link` — the ``t.me/<bot>?start=trip_<token>`` URL that
  the dispatcher shares with the cargo owner.
* Text templating helpers (:func:`format_status_change`, :func:`format_daily_update`)
  so both the scheduler and the trip-advance path can produce identical
  message copy.

The module deliberately holds no state: config is read from ``settings`` on
every call so hot-reloading the bot token doesn't require an app restart.
"""
from __future__ import annotations

import html
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx

from app.core.config import settings
from app.core.logging import logger
from app.models.enums import TripStatus


_TELEGRAM_API = "https://api.telegram.org"
_REQUEST_TIMEOUT_S = 10.0


@dataclass(frozen=True)
class SendResult:
    """Outcome of one Telegram sendMessage call.

    ``ok`` mirrors Telegram's own ``ok`` field. ``permanently_failed`` is
    True when the chat is unreachable in a way that retrying won't fix (403
    Forbidden = user blocked bot; 400 chat not found = chat deleted). The
    scheduler uses that hint to disable the subscription so we don't hammer
    a dead chat every morning.
    """

    ok: bool
    status_code: int
    permanently_failed: bool = False


async def send_message(chat_id: str, text: str, *, disable_notification: bool = False) -> SendResult:
    """Send a plain-text (HTML-formatted) message to a Telegram chat.

    Never raises: any transport / auth failure is logged and reflected in the
    returned :class:`SendResult`. Callers in scheduler batches should keep
    going on ``ok=False`` rather than aborting the whole tick.
    """
    if not settings.telegram_configured:
        return SendResult(ok=False, status_code=0)

    url = f"{_TELEGRAM_API}/bot{settings.telegram_bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
        "disable_notification": disable_notification,
    }
    try:
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_S) as client:
            resp = await client.post(url, json=payload)
    except httpx.HTTPError as exc:
        logger.warning("telegram_send_transport_error", chat_id=chat_id, error=str(exc))
        return SendResult(ok=False, status_code=0)

    if resp.status_code == 200:
        return SendResult(ok=True, status_code=200)

    # Common permanent failures — see https://core.telegram.org/bots/api#making-requests
    permanent = resp.status_code in (400, 403)
    logger.warning(
        "telegram_send_failed",
        chat_id=chat_id,
        status=resp.status_code,
        body=resp.text[:200],
    )
    return SendResult(ok=False, status_code=resp.status_code, permanently_failed=permanent)


async def register_webhook() -> None:
    """Best-effort ``setWebhook`` registration against Telegram's Bot API.

    Called once at app startup so the bot actually receives updates without a
    manual ``curl`` step after every deploy. Never raises: a missing
    ``PUBLIC_API_URL`` or an unreachable Telegram API is logged and skipped —
    this is a convenience, not something that should block app startup.
    """
    if not settings.telegram_configured:
        return

    base_url = settings.public_api_url.strip().rstrip("/")
    if not base_url:
        logger.warning(
            "telegram_webhook_registration_skipped",
            reason="PUBLIC_API_URL not set",
        )
        return

    webhook_url = f"{base_url}/api/telegram/webhook"
    url = f"{_TELEGRAM_API}/bot{settings.telegram_bot_token}/setWebhook"
    payload = {
        "url": webhook_url,
        "secret_token": settings.telegram_webhook_secret,
    }
    try:
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_S) as client:
            resp = await client.post(url, json=payload)
        if resp.status_code == 200 and resp.json().get("ok"):
            logger.info("telegram_webhook_registered", webhook_url=webhook_url)
        else:
            logger.warning(
                "telegram_webhook_registration_failed",
                status=resp.status_code,
                body=resp.text[:200],
            )
    except httpx.HTTPError as exc:
        logger.warning("telegram_webhook_registration_transport_error", error=str(exc))
    except Exception:  # noqa: BLE001 — never let this block app startup.
        logger.exception("telegram_webhook_registration_unexpected_error")


def build_deep_link(token: str) -> str:
    """The magic link the dispatcher shares with the cargo owner.

    Falls back to a plain start-parameter URL when the bot username is not
    configured, so the link is still copy-pasteable — the customer opens
    Telegram, searches the bot, and pastes ``/start trip_<token>`` manually.
    """
    username = settings.telegram_bot_username.strip().lstrip("@")
    if username:
        return f"https://t.me/{username}?start=trip_{token}"
    return f"tg://resolve?start=trip_{token}"


# ── Message templates ────────────────────────────────────────────────────
#
# All text is authored in Uzbek because that is the market this platform
# targets and the cargo owner is guaranteed to be a local shipper. Add ru/en
# variants later based on ``TripSubscription.language`` when we start seeing
# non-Uzbek subscribers.


_STATUS_LABEL_UZ: dict[TripStatus, str] = {
    TripStatus.draft: "reja tuzilmoqda",
    TripStatus.planned: "rejalashtirildi",
    TripStatus.loading: "yuklanmoqda",
    TripStatus.en_route: "yo'lda",
    TripStatus.at_border: "chegarada",
    TripStatus.delivered: "yetkazildi",
    TripStatus.cancelled: "bekor qilindi",
}


def _status_label(status: TripStatus | None) -> str:
    if status is None:
        return "noma'lum"
    return _STATUS_LABEL_UZ.get(status, status.value)


def _fmt_coords(lat: float | None, lng: float | None) -> str:
    """Google Maps link on any coordinates — reverse-geocoding is a V2 job."""
    if lat is None or lng is None:
        return "joylashuv hozircha aniqlanmagan"
    return f'<a href="https://maps.google.com/?q={lat},{lng}">xaritada ko\'rish</a>'


def format_activation(trip_reference: str, cargo: str | None) -> str:
    """First message the cargo owner sees after clicking the deep link."""
    safe_reference = html.escape(trip_reference)
    cargo_line = f"\n📦 Yuk: {html.escape(cargo)}" if cargo else ""
    return (
        f"👋 Salom! Siz endi <b>{safe_reference}</b> reysining kuzatuvchisisiz."
        f"{cargo_line}\n\n"
        "Har kuni ertalab yukning joylashuvi haqida qisqa xabar olib turasiz. "
        "Yuk holati o'zgarganda ham darhol xabar beriladi.\n\n"
        "Sozlamalar: /settings — kunlik/tezkor xabarlarni yoqish yoki o'chirish."
    )


def format_status_change(
    trip_reference: str,
    to_status: TripStatus,
    lat: float | None,
    lng: float | None,
    note: str | None = None,
) -> str:
    """Event-based push: driver moved the trip through its timeline."""
    note_line = f"\n📝 {html.escape(note)}" if note else ""
    return (
        f"🚚 <b>{html.escape(trip_reference)}</b>\n"
        f"Holati: <b>{_status_label(to_status)}</b>\n"
        f"📍 {_fmt_coords(lat, lng)}"
        f"{note_line}"
    )


def format_daily_update(
    trip_reference: str,
    status: TripStatus | None,
    lat: float | None,
    lng: float | None,
    destination: str | None,
    speed_kmh: float | None,
    updated_at: datetime | None,
) -> str:
    """Morning digest: current status + last-known position + destination."""
    dest_line = f"\n🎯 Manzil: {html.escape(destination)}" if destination else ""
    speed_line = ""
    if speed_kmh and speed_kmh > 5:
        speed_line = f"\n🏃 Tezlik: {int(speed_kmh)} km/soat"
    elif speed_kmh is not None:
        speed_line = "\n⏸ Yuk hozir to'xtab turibdi"
    fresh_line = ""
    if updated_at is not None:
        fresh_line = f"\n🕒 Oxirgi ma'lumot: {updated_at.strftime('%d.%m %H:%M')} UTC"
    return (
        f"🌅 Ertalabki xabar — <b>{html.escape(trip_reference)}</b>\n"
        f"Holati: <b>{_status_label(status)}</b>\n"
        f"📍 {_fmt_coords(lat, lng)}"
        f"{dest_line}{speed_line}{fresh_line}"
    )


def parse_start_command(text: str) -> str | None:
    """Return the subscription token from a ``/start trip_<token>`` payload.

    Telegram delivers the deep-link parameter as ``/start trip_<token>``
    (single argument, space-separated). Non-start commands and malformed
    payloads return ``None`` so the webhook can silently ignore them.
    """
    if not text:
        return None
    parts = text.strip().split(maxsplit=1)
    if not parts or parts[0] != "/start":
        return None
    if len(parts) != 2:
        return None
    payload = parts[1].strip()
    if not payload.startswith("trip_"):
        return None
    token = payload[len("trip_"):]
    # Tokens are URL-safe base64 (see secrets.token_urlsafe). Reject anything
    # that couldn't have been minted here so we don't burn a DB round-trip on
    # obviously bogus input.
    if not token or len(token) > 48 or not all(
        c.isalnum() or c in "-_" for c in token
    ):
        return None
    return token


def extract_chat(update: dict[str, Any]) -> dict[str, Any] | None:
    """Pull the ``message.chat`` dict out of an incoming update, if present."""
    message = update.get("message") or update.get("edited_message")
    if not isinstance(message, dict):
        return None
    chat = message.get("chat")
    if not isinstance(chat, dict) or "id" not in chat:
        return None
    return chat


def extract_text(update: dict[str, Any]) -> str:
    """Pull the message text (empty string on non-text updates)."""
    message = update.get("message") or update.get("edited_message") or {}
    text = message.get("text")
    return text if isinstance(text, str) else ""
