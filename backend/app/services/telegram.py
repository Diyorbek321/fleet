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
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import httpx

from app.core.config import settings
from app.core.logging import logger
from app.models.enums import StagePlace, TripStage, TripStatus


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
    # Telegram's id for the sent message — what :func:`pin_message` needs.
    message_id: int | None = None


async def send_message(
    chat_id: str,
    text: str,
    *,
    disable_notification: bool = False,
    reply_markup: dict[str, Any] | None = None,
) -> SendResult:
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
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    try:
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_S) as client:
            resp = await client.post(url, json=payload)
    except httpx.HTTPError as exc:
        logger.warning("telegram_send_transport_error", chat_id=chat_id, error=str(exc))
        return SendResult(ok=False, status_code=0)

    if resp.status_code == 200:
        return SendResult(ok=True, status_code=200, message_id=_message_id(resp))

    # Common permanent failures — see https://core.telegram.org/bots/api#making-requests
    permanent = resp.status_code in (400, 403)
    logger.warning(
        "telegram_send_failed",
        chat_id=chat_id,
        status=resp.status_code,
        body=resp.text[:200],
    )
    return SendResult(ok=False, status_code=resp.status_code, permanently_failed=permanent)


def _message_id(resp: httpx.Response) -> int | None:
    """The sent message's id, or ``None`` if Telegram's body is not what we expect."""
    try:
        message_id = resp.json().get("result", {}).get("message_id")
    except (ValueError, AttributeError):
        return None
    return message_id if isinstance(message_id, int) else None


async def pin_message(chat_id: str, message_id: int) -> bool:
    """Pin one message to the top of a chat, silently. Never raises.

    Used for the cargo owner's map button: it is sent once per trip, so it
    has to stay findable after a week of status cards have scrolled past it.
    A failed pin costs only convenience — the message itself is already sent.
    """
    if not settings.telegram_configured:
        return False
    url = f"{_TELEGRAM_API}/bot{settings.telegram_bot_token}/pinChatMessage"
    payload = {"chat_id": chat_id, "message_id": message_id, "disable_notification": True}
    try:
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_S) as client:
            resp = await client.post(url, json=payload)
    except httpx.HTTPError as exc:
        logger.warning("telegram_pin_transport_error", chat_id=chat_id, error=str(exc))
        return False
    if resp.status_code != 200:
        logger.warning(
            "telegram_pin_failed", chat_id=chat_id, status=resp.status_code, body=resp.text[:200]
        )
        return False
    return True


def link_button(label: str, url: str) -> dict[str, Any]:
    """An inline keyboard holding a single URL button."""
    return {"inline_keyboard": [[{"text": label, "url": url}]]}


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
# All text is authored in Russian: it is the working language across the
# Uzbekistan–Kazakhstan–Russia corridor these trips run, and the one every
# cargo owner on the route reads. Add uz/en variants later based on
# ``TripSubscription.language`` when we start seeing subscribers who need them.


_STATUS_LABEL_RU: dict[TripStatus, str] = {
    TripStatus.draft: "черновик",
    TripStatus.planned: "запланирован",
    TripStatus.loading: "погрузка",
    TripStatus.en_route: "в пути",
    TripStatus.at_border: "на границе",
    TripStatus.delivered: "доставлен",
    TripStatus.cancelled: "отменён",
}


def _status_label(status: TripStatus | None) -> str:
    if status is None:
        return "неизвестно"
    return _STATUS_LABEL_RU.get(status, status.value)


def _fmt_coords(lat: float | None, lng: float | None) -> str:
    """Google Maps link on any coordinates, with no claim about where that is."""
    if lat is None or lng is None:
        return "местоположение пока не определено"
    return f'<a href="https://maps.google.com/?q={lat},{lng}">посмотреть на карте</a>'


def _fmt_location(
    lat: float | None, lng: float | None, place: str | None, *, with_link: bool = True
) -> str:
    """The location block: country and city if we know them, then the map link.

    ``place`` comes from :mod:`app.services.geocoding` and is ``None`` whenever
    the geocoder was off, unreachable or unsure — in which case this degrades
    to exactly the link-only line the bot sent before, which is why callers can
    pass it unconditionally.

    ``with_link=False`` drops the coordinate link for a message that carries a
    better one of its own; with no place either, the coordinates are still
    printed, because "where is my cargo" has to be answered somehow.
    """
    if not place:
        if with_link:
            return _fmt_coords(lat, lng)
        if lat is None or lng is None:
            return "местоположение пока не определено"
        return f"{lat}, {lng}"
    if not with_link:
        return html.escape(place, quote=False)
    # quote=False for the same reason the alert bus uses it: these place names
    # are transliterated and many of them carry an apostrophe.
    line = html.escape(place, quote=False)
    if lat is None or lng is None:
        return line
    return f"{line}\n   {_fmt_coords(lat, lng)}"


TRACK_BUTTON_LABEL = "🗺 Где машина?"


def format_activation(trip_reference: str, cargo: str | None, *, has_map: bool = False) -> str:
    """First message the cargo owner sees after clicking the deep link.

    With a map it is also the only time the map link is sent on its own: the
    button under this message opens the live page for the whole trip, so the
    owner is told to tap it rather than wait for a daily message.
    """
    safe_reference = html.escape(trip_reference)
    cargo_line = f"\n📦 Груз: {html.escape(cargo)}" if cargo else ""
    map_line = (
        "Нажмите кнопку «Где машина?» под этим сообщением — каждый раз откроется карта "
        "с текущим положением машины. Сообщение закреплено вверху чата.\n\n"
        if has_map
        else ""
    )
    return (
        f"👋 Здравствуйте! Вы подписаны на отслеживание рейса <b>{safe_reference}</b>."
        f"{cargo_line}\n\n"
        f"{map_line}"
        "При изменении статуса груза сообщение придёт сразу.\n\n"
        "Настройки: /settings · отключить все сообщения: /stop"
    )


def format_status_change(
    trip_reference: str,
    to_status: TripStatus,
    lat: float | None,
    lng: float | None,
    note: str | None = None,
    place: str | None = None,
) -> str:
    """Event-based push: driver moved the trip through its timeline."""
    note_line = f"\n📝 {html.escape(note)}" if note else ""
    return (
        f"🚚 <b>{html.escape(trip_reference)}</b>\n"
        f"Статус: <b>{_status_label(to_status)}</b>\n"
        f"📍 {_fmt_location(lat, lng, place)}"
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
    place: str | None = None,
) -> str:
    """Morning digest: current status + last-known position + destination."""
    dest_line = f"\n🎯 Пункт назначения: {html.escape(destination)}" if destination else ""
    speed_line = ""
    if speed_kmh and speed_kmh > 5:
        speed_line = f"\n🏃 Скорость: {int(speed_kmh)} км/ч"
    elif speed_kmh is not None:
        speed_line = "\n⏸ Груз сейчас стоит"
    fresh_line = ""
    if updated_at is not None:
        fresh_line = f"\n🕒 Последние данные: {updated_at.strftime('%d.%m %H:%M')} UTC"
    return (
        f"🌅 Утренняя сводка — <b>{html.escape(trip_reference)}</b>\n"
        f"Статус: <b>{_status_label(status)}</b>\n"
        f"📍 {_fmt_location(lat, lng, place)}"
        f"{dest_line}{speed_line}{fresh_line}"
    )


# ── The customer's card ──────────────────────────────────────────────────
#
# One shape, whatever the reason for sending it: the morning digest and a
# checkpoint the driver just reported print the same seven lines. A customer
# who gets two differently-shaped messages about one load reads the second one
# looking for what changed, which is exactly the work this is meant to save.

_STAGE_LABEL_RU: dict[TripStage, str] = {
    TripStage.arrived_loading: "Прибыл на погрузку",
    TripStage.loaded_waiting_docs: "Погрузился, жду документы",
    TripStage.docs_received_en_route: "Взял документы, еду",
    TripStage.arrived_border: "На границе",
    TripStage.crossed_border: "Прошёл границу",
    TripStage.arrived_customs: "Прибыл на растаможку",
    TripStage.left_customs: "Выехал с растаможки",
    TripStage.arrived_unloading: "Прибыл на выгрузку",
    TripStage.unloaded: "Выгрузился",
}

_PLACE_LABEL_RU: dict[StagePlace, str] = {
    StagePlace.uz: "УЗБ",
    StagePlace.kz: "КЗ",
    StagePlace.ru: "РФ",
    StagePlace.uz_kz: "УЗБ–КЗ",
    StagePlace.kz_ru: "КЗ–РФ",
}


def stage_label(stage: TripStage | None, place: StagePlace | None) -> str:
    """"На границе УЗБ–КЗ" — the checkpoint and where, in one line.

    Falls back to the coarse status wording when no checkpoint has been
    reported yet, so a trip that predates the feature still reads as something
    rather than as a blank.
    """
    if stage is None:
        return "—"
    label = _STAGE_LABEL_RU.get(stage, stage.value)
    return f"{label} {_PLACE_LABEL_RU[place]}" if place else label


def format_customer_card(
    *,
    org_name: str,
    reference: str,
    origin: str | None,
    destination: str | None,
    loaded_at: datetime | None,
    plate: str | None,
    place: str | None,
    lat: float | None,
    lng: float | None,
    eta_customs: date | None,
    eta_is_measured: bool = False,
    cargo: str | None = None,
    note: str | None = None,
    track_url: str | None = None,
    stage: str | None = None,
    position_at: str | None = None,
) -> str:
    """The lines a cargo owner asked us for, in their order.

    Every line that has no value is dropped rather than printed with a dash: a
    card with four real lines reads as a status report, the same card padded out
    with "—" reads as a broken system.

    There is deliberately no status line. The customer's question is where the
    load is and when it lands, and both are answered above and below where a
    status would have sat; a word like "в пути" next to a live position and a
    date only invited "so which is it?" on the phone.

    ``stage`` and ``position_at`` are for the copy a dispatcher pastes by hand,
    which is asked for by status and read later than it was written; the bot
    never passes them.
    """
    e = lambda v: html.escape(str(v), quote=False)  # noqa: E731

    lines = [f"<b>{e(org_name)}</b>", ""]

    route = " — ".join(p for p in (origin, destination) if p)
    if route:
        lines.append(f"Маршрут: <b>{e(route)}</b>")
    lines.append(f"Рейс: {e(reference)}")
    if cargo:
        lines.append(f"Груз: {e(cargo)}")
    if loaded_at is not None:
        lines.append(f"Дата погрузки: {loaded_at.strftime('%d.%m.%Y')}")
    if plate:
        lines.append(f"ТС: {e(plate)}")
    if stage:
        lines.append(f"Статус: <b>{e(stage)}</b>")

    # The bare-coordinate Google Maps link is the fallback, not the default:
    # once there is a tracking page the card ends with a link to it, and two
    # lines a thumb apart both reading "посмотреть на карте" is a question, not
    # a service. With no tracking page configured the coordinate link is still
    # the only way to answer "where", so it stays.
    where = _fmt_location(lat, lng, place, with_link=not track_url)
    lines.append(f"Текущее местоположение ТС: {where}")
    if position_at:
        lines.append(f"Данные от: {e(position_at)}")

    if eta_customs is not None:
        # "ориентировочно" is not hedging for its own sake: until a corridor has
        # a history behind it the date is a formula's answer, and a customer who
        # is told that plans around it differently.
        suffix = "" if eta_is_measured else " (ориентировочно)"
        lines.append(
            f"Ожидаемая дата прибытия на растаможку: <b>"
            f"{eta_customs.strftime('%d.%m.%Y')}</b>{suffix}"
        )

    if note:
        lines.append(f"📝 {e(note)}")

    if track_url:
        # Last and visually separate, because it is the only thing in the card
        # that is an action rather than a fact. A coordinate pair answers
        # "where" only to someone willing to paste it somewhere; this opens the
        # lorry on a map with its plate on it, which is what was asked for.
        lines.append("")
        lines.append(
            f'🗺 <a href="{html.escape(track_url, quote=True)}">Посмотреть на карте</a>'
        )

    return "\n".join(lines)


_LINK_RE = re.compile(r'<a href="([^"]*)">(.*?)</a>')
_TAG_RE = re.compile(r"<[^>]+>")


def to_plain_text(text: str) -> str:
    """A Telegram HTML message as text to paste anywhere else.

    A link keeps its address after its label — dropping the tag alone would
    leave "посмотреть на карте" pointing nowhere.
    """
    text = _LINK_RE.sub(lambda m: f"{m.group(2)}: {html.unescape(m.group(1))}", text)
    return html.unescape(_TAG_RE.sub("", text))


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
