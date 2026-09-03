"""Telegram bot webhook + dispatcher-facing subscription management.

Two audiences share this file, separated by URL:

* **Public webhook** — ``POST /api/telegram/webhook``. Called by Telegram
  when a cargo owner sends the bot ``/start trip_<token>`` (or later /settings
  /stop). No app auth: authenticity is verified via the secret token header
  Telegram echoes back from the setWebhook call.

* **Dispatcher API** — ``/api/trip-subscriptions/...``. Regular org-scoped
  admin/manager endpoints for creating a subscription, listing them per
  trip, regenerating tokens, and disabling. These never expose ``chat_id``
  to the frontend so the dispatcher can't hijack a chat.

The webhook is intentionally best-effort: any exception is logged and swallowed
so Telegram doesn't retry a bad payload forever, and unknown / malformed
updates return 200 OK.
"""
from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.logging import logger
from app.core.rate_limit import limiter
from app.deps.auth import get_org_id, require_role
from app.models.enums import UserRole
from app.models.notifications import TripSubscription
from app.models.trips import Trip
from app.services.owner_alerts.commands import (
    activate_owner_chat,
    handle_owner_message,
    parse_owner_start,
)
from app.services.telegram import (
    build_deep_link,
    extract_chat,
    extract_text,
    format_activation,
    parse_start_command,
    send_message,
)


# ── Public webhook ────────────────────────────────────────────────────────

webhook_router = APIRouter(prefix="/api/telegram", tags=["Telegram"])


def _feature_enabled() -> None:
    """Guard used by every telegram-owned route. 404 when disabled so we don't
    advertise the endpoint at all in envs where the bot isn't configured."""
    if not settings.telegram_configured:
        raise HTTPException(status_code=404, detail="Not found")


@webhook_router.post("/webhook")
@limiter.limit("60/minute")  # generous for legitimate Telegram traffic, blocks spoofed floods
async def telegram_webhook(
    request: Request,
    payload: dict[str, Any] = Body(...),
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Consume an incoming Telegram update.

    Handles ``/start trip_<token>`` (subscribe), ``/stop`` (unsubscribe) and
    ``/settings`` (show current toggles). Anything else gets a friendly
    fallback so bot users never hit a hard silence.
    """
    _feature_enabled()

    # Verify the secret token when configured. Missing/mismatch → 401; we
    # don't want to give Telegram an easy way to accept spoofed updates.
    expected = settings.telegram_webhook_secret.strip()
    if expected and x_telegram_bot_api_secret_token != expected:
        logger.warning("telegram_webhook_secret_mismatch")
        raise HTTPException(status_code=401, detail="Invalid webhook secret")

    try:
        await _handle_update(db, payload)
    except Exception:  # noqa: BLE001 — never let a bad update trigger retries.
        logger.exception("telegram_webhook_handler_failed")

    # Always 200 so Telegram doesn't retry storms.
    return Response(status_code=200)


async def _handle_update(db: AsyncSession, update: dict[str, Any]) -> None:
    chat = extract_chat(update)
    if chat is None:
        return
    chat_id = str(chat["id"])
    text = extract_text(update)

    # One bot serves two audiences, so the deep-link payload carries a
    # namespace: ``owner_`` binds a company's own chat to its alert stream,
    # ``trip_`` binds a cargo owner to one shipment. Checking the owner prefix
    # first costs nothing — the parsers reject each other's payloads outright.
    owner_token = parse_owner_start(text)
    if owner_token:
        username = chat.get("username") if isinstance(chat, dict) else None
        reply = await activate_owner_chat(db, owner_token, chat_id, username)
        await send_message(chat_id, reply)
        return

    token = parse_start_command(text)
    if token:
        await _activate_subscription(db, token, chat_id, chat, text)
        return

    # An already-linked owner chat answers its own commands. ``None`` means the
    # chat has no owner link at all, so everything below — the cargo owner's
    # /stop and /settings — keeps behaving exactly as it did.
    owner_reply = await handle_owner_message(db, chat_id, text)
    if owner_reply is not None:
        await send_message(chat_id, owner_reply)
        return

    stripped = text.strip().lower()
    if stripped in ("/stop", "/stop@" + settings.telegram_bot_username.lower()):
        await _stop_all_for_chat(db, chat_id)
        await send_message(
            chat_id,
            "🛑 Barcha xabarlar o'chirildi. Yangi reys uchun dispetcherdan yangi havola so'rang.",
        )
        return

    if stripped.startswith("/settings"):
        await _send_settings(db, chat_id)
        return

    if stripped.startswith("/start"):
        # Bare /start (no token) — friendly onboarding blurb.
        await send_message(
            chat_id,
            "👋 Salom! Bu yuk kuzatuv boti. Dispetcher yuborgan havolani bosing yoki "
            "<code>/start trip_TOKEN</code> ko'rinishida token yuboring.",
        )
        return

    # Any other message: hint at the available commands so a lost user finds
    # their way back without a human having to intervene.
    await send_message(
        chat_id,
        "🤖 Buyruqlar:\n"
        "/settings — obunalar va sozlamalar\n"
        "/stop — barcha xabarlarni o'chirish",
    )


async def _activate_subscription(
    db: AsyncSession,
    token: str,
    chat_id: str,
    chat: dict[str, Any],
    _text: str,
) -> None:
    """Bind the incoming Telegram chat to the subscription identified by ``token``."""
    sub = (
        await db.execute(select(TripSubscription).where(TripSubscription.token == token))
    ).scalar_one_or_none()
    if sub is None:
        await send_message(
            chat_id,
            "❌ Havola noto'g'ri yoki eskirgan. Dispetcherdan yangisini so'rang.",
        )
        return

    # Trip metadata for the welcome message — best-effort; a missing trip is
    # weird but we still want the activation to succeed.
    trip = (
        await db.execute(select(Trip).where(Trip.id == sub.trip_id))
    ).scalar_one_or_none()

    sub.chat_id = chat_id
    sub.activated_at = sub.activated_at or datetime.now(timezone.utc)
    sub.username = (chat.get("username") or None) if isinstance(chat, dict) else None
    # Some clients don't send language_code on chats; leave prior value alone.
    lang = chat.get("language_code") if isinstance(chat, dict) else None
    if isinstance(lang, str) and lang:
        sub.language = lang[:10]
    await db.commit()

    ref = trip.reference if trip else "reys"
    cargo = trip.cargo_description if trip else None
    await send_message(chat_id, format_activation(ref, cargo))


async def _stop_all_for_chat(db: AsyncSession, chat_id: str) -> None:
    """Silence every subscription bound to this chat.

    We disable the toggles rather than deleting rows so the dispatcher still
    sees "this customer unsubscribed" in the panel.
    """
    subs = (
        await db.execute(select(TripSubscription).where(TripSubscription.chat_id == chat_id))
    ).scalars().all()
    for sub in subs:
        sub.daily_enabled = False
        sub.event_enabled = False
    if subs:
        await db.commit()


async def _send_settings(db: AsyncSession, chat_id: str) -> None:
    subs = (
        await db.execute(select(TripSubscription).where(TripSubscription.chat_id == chat_id))
    ).scalars().all()
    if not subs:
        await send_message(chat_id, "Sizda hozircha faol obuna yo'q.")
        return

    # Batch-fetch all referenced trips in one query instead of one query per
    # subscription — a chat can be subscribed to many trips.
    trip_ids = {sub.trip_id for sub in subs}
    trips = (
        await db.execute(select(Trip).where(Trip.id.in_(trip_ids)))
    ).scalars().all()
    trip_by_id = {t.id: t for t in trips}

    lines = ["📋 <b>Faol obunalar:</b>"]
    for sub in subs:
        trip = trip_by_id.get(sub.trip_id)
        ref = trip.reference if trip else str(sub.trip_id)[:8]
        daily = "✅" if sub.daily_enabled else "❌"
        event = "✅" if sub.event_enabled else "❌"
        lines.append(f"• <b>{ref}</b> — kunlik: {daily}, tezkor: {event}")
    lines.append("\nBarcha xabarlarni o'chirish: /stop")
    await send_message(chat_id, "\n".join(lines))


# ── Dispatcher API (auth'd) ──────────────────────────────────────────────

api_router = APIRouter(prefix="/api/trip-subscriptions", tags=["Trip Subscriptions"])

_MANAGE = require_role(UserRole.admin, UserRole.manager, UserRole.operator)


class SubscriptionCreate(BaseModel):
    trip_id: uuid.UUID
    contact_name: str | None = Field(default=None, max_length=200)
    contact_phone: str | None = Field(default=None, max_length=40)


class SubscriptionOut(BaseModel):
    id: uuid.UUID
    trip_id: uuid.UUID
    contact_name: str | None
    contact_phone: str | None
    daily_enabled: bool
    event_enabled: bool
    activated: bool
    activated_at: str | None
    deep_link: str

    model_config = {"from_attributes": True}


def _to_out(sub: TripSubscription) -> SubscriptionOut:
    return SubscriptionOut(
        id=sub.id,
        trip_id=sub.trip_id,
        contact_name=sub.contact_name,
        contact_phone=sub.contact_phone,
        daily_enabled=sub.daily_enabled,
        event_enabled=sub.event_enabled,
        activated=sub.chat_id is not None,
        activated_at=sub.activated_at.isoformat() if sub.activated_at else None,
        deep_link=build_deep_link(sub.token),
    )


@api_router.post("", response_model=SubscriptionOut, status_code=201)
async def create_subscription(
    data: SubscriptionCreate,
    db: AsyncSession = Depends(get_db),
    org: uuid.UUID = Depends(get_org_id),
    _user=Depends(_MANAGE),
):
    """Mint a subscription magic link for a trip.

    The trip must belong to the caller's organization. The token is generated
    server-side and shown once via the deep link; the dispatcher shares that
    link with the cargo owner over any channel (Telegram, SMS, WhatsApp).

    This works even when the Telegram bot itself isn't configured yet (see
    ``settings.telegram_bot_token``), so dispatchers can be onboarded ahead
    of a bot being provisioned; the deep link simply won't activate until
    the bot is live.
    """
    trip = (
        await db.execute(select(Trip).where(Trip.id == data.trip_id, Trip.org_id == org))
    ).scalar_one_or_none()
    if trip is None:
        raise HTTPException(status_code=404, detail="Trip not found")

    sub = TripSubscription(
        org_id=org,
        trip_id=trip.id,
        token=secrets.token_urlsafe(16),
        contact_name=data.contact_name,
        contact_phone=data.contact_phone,
    )
    db.add(sub)
    await db.commit()
    await db.refresh(sub)
    return _to_out(sub)


@api_router.get("", response_model=list[SubscriptionOut])
async def list_subscriptions(
    trip_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    org: uuid.UUID = Depends(get_org_id),
    _user=Depends(_MANAGE),
):
    """List subscriptions for the caller's org, optionally filtered to one trip."""
    stmt = select(TripSubscription).where(TripSubscription.org_id == org)
    if trip_id is not None:
        stmt = stmt.where(TripSubscription.trip_id == trip_id)
    subs = (await db.execute(stmt.order_by(TripSubscription.created_at.desc()))).scalars().all()
    return [_to_out(s) for s in subs]


@api_router.delete("/{sub_id}", status_code=204)
async def delete_subscription(
    sub_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    org: uuid.UUID = Depends(get_org_id),
    _user=Depends(_MANAGE),
):
    sub = (
        await db.execute(
            select(TripSubscription).where(TripSubscription.id == sub_id, TripSubscription.org_id == org)
        )
    ).scalar_one_or_none()
    if sub is None:
        raise HTTPException(status_code=404, detail="Subscription not found")
    await db.delete(sub)
    await db.commit()
    return Response(status_code=204)
