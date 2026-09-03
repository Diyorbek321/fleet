"""The one gated path from "something happened" to "the owner's phone buzzed".

Every watcher in this package builds an :class:`Alert` and hands it to
:func:`notify_owner`. Nothing sends to an owner any other way, because every
rule that keeps this feature usable lives here and a second path would bypass
all of them:

* **Dedupe.** The scheduler ticks every fifteen minutes. Its jobs are
  idempotent — messages are not. ``Alert.dedupe_key`` names the *fact*
  ("interval <id> is overdue"), never the sentence describing it, so an
  unchanged fact is announced once and a changed one gets through.
* **Quiet hours suppress without recording.** A non-critical alert dropped for
  arriving at 03:00 must still arrive at 08:00. Writing its dedupe row would
  mean the owner never hears about it at all, so the row is skipped and the
  next tick after the window delivers it. Critical alerts ignore the window.
* **Per-chat mute list and minimum severity.** Alert fatigue is how this
  feature dies; an owner who mutes the bot in week two does not come back.
  They get to turn down the parts they do not want instead of all of it.
* **Failure is contained.** Nothing here raises. A scheduler tick must survive
  a blocked bot, an unreachable Telegram, and a malformed alert alike.

Dedupe is scoped to the organization, not the chat: several chats in one
company are several people reading about the same truck, and telling them each
once is the point. The trade-off is that a chat inside its quiet window when
another chat is served will not get a delayed copy — the fact is already
recorded as reported.
"""
from __future__ import annotations

import html
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable

import httpx
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import logger
from app.models.owner_alerts import (
    SEVERITY_RANK,
    AlertKind,
    AlertSeverity,
    NotificationLog,
    TelegramAccount,
)
from app.services.period_reports import report_tz
from app.services.telegram import SendResult, send_message

__all__ = [
    "Alert",
    "AlertKind",
    "AlertSeverity",
    "notify_owner",
    "send_owner_document",
    "render_alert",
    "prune_notification_log",
]

_TELEGRAM_API = "https://api.telegram.org"
_DOCUMENT_TIMEOUT_S = 30.0


@dataclass(frozen=True)
class Alert:
    """One thing worth telling an owner about.

    ``title`` is a single Uzbek line with no markup — it is escaped on the way
    out. ``body`` is the opposite: already-escaped HTML lines separated by
    newlines, because a watcher composing a table of numbers needs ``<b>`` and
    escaping it again would show the tags.
    """

    kind: AlertKind
    severity: AlertSeverity
    title: str
    body: str
    dedupe_key: str
    dedupe_ttl_hours: int = 24
    path: str | None = None


_SEVERITY_ICON: dict[AlertSeverity, str] = {
    AlertSeverity.info: "ℹ️",
    AlertSeverity.warning: "⚠️",
    AlertSeverity.critical: "🚨",
}


# ── Rendering ────────────────────────────────────────────────────────────


def _panel_base_url() -> str:
    """Externally reachable base URL of the web panel.

    Read from ``PUBLIC_WEB_URL`` when set, otherwise the first configured CORS
    origin — which is by definition the browser app allowed to call this API,
    so in every real deployment it is already the right answer. An empty
    result simply drops the link from the message rather than shipping a
    ``None/trips/…`` href.
    """
    explicit = (settings.public_web_url or os.environ.get("PUBLIC_WEB_URL", "")).strip()
    if explicit:
        return explicit.rstrip("/")
    origins = settings.cors_origins_list()
    return origins[0].rstrip("/") if origins else ""


def _panel_link(path: str | None) -> str | None:
    if not path:
        return None
    base = _panel_base_url()
    if not base:
        return None
    return f"{base}/{path.lstrip('/')}"


def render_alert(alert: Alert) -> str:
    """The exact HTML text a chat receives. Pure, so it is testable alone."""
    icon = _SEVERITY_ICON.get(alert.severity, "•")
    # quote=False: the title is text content, not an attribute value, and
    # escaping apostrophes turns every Uzbek word like "yoqilg'i" into
    # "yoqilg&#x27;i" in anything that reads the message as plain text.
    parts = [f"{icon} <b>{html.escape(alert.title, quote=False)}</b>"]
    if alert.body:
        parts.append(alert.body)
    link = _panel_link(alert.path)
    if link:
        parts.append(f'<a href="{html.escape(link, quote=True)}">🔗 Panelda ochish</a>')
    return "\n\n".join(parts)


# ── Recipient gating ─────────────────────────────────────────────────────


def _in_quiet_hours(account: TelegramAccount, now_local_hour: int) -> bool:
    """Whether ``now`` falls inside this chat's overnight window.

    Wraps midnight when ``from > to`` (22→07 is the default). Equal bounds mean
    "no window": reading them as a 24-hour window would silence an owner
    permanently because of a slip in a settings form.
    """
    start = account.quiet_from_hour
    end = account.quiet_to_hour
    if start is None or end is None or start == end:
        return False
    if start < end:
        return start <= now_local_hour < end
    return now_local_hour >= start or now_local_hour < end


def _wants(account: TelegramAccount, kind: AlertKind, severity: AlertSeverity) -> bool:
    """Mute list + minimum severity. Independent of the time of day."""
    if kind.value in (account.muted_kinds or []):
        return False
    minimum = SEVERITY_RANK.get(account.min_severity, SEVERITY_RANK[AlertSeverity.warning])
    return SEVERITY_RANK[severity] >= minimum


async def _load_chats(db: AsyncSession, org_id: uuid.UUID) -> list[TelegramAccount]:
    """Every chat in the org that could be written to right now."""
    rows = (
        await db.execute(
            select(TelegramAccount).where(
                TelegramAccount.org_id == org_id,
                TelegramAccount.is_active.is_(True),
                TelegramAccount.chat_id.is_not(None),
            )
        )
    ).scalars().all()
    return list(rows)


def _split_recipients(
    chats: list[TelegramAccount], kind: AlertKind, severity: AlertSeverity
) -> tuple[list[TelegramAccount], bool]:
    """Partition chats into "send now" and "would have wanted this, but it is
    the middle of the night". The second half is returned as a flag because it
    is the one condition that must not write a dedupe row.
    """
    hour = datetime.now(report_tz()).hour
    recipients: list[TelegramAccount] = []
    deferred = False
    for chat in chats:
        if not _wants(chat, kind, severity):
            continue
        if severity is not AlertSeverity.critical and _in_quiet_hours(chat, hour):
            deferred = True
            continue
        recipients.append(chat)
    return recipients, deferred


# ── Dedupe bookkeeping ───────────────────────────────────────────────────


async def _already_reported(
    db: AsyncSession, org_id: uuid.UUID, dedupe_key: str, ttl_hours: int
) -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max(0, ttl_hours))
    row = (
        await db.execute(
            select(NotificationLog.sent_at).where(
                NotificationLog.org_id == org_id,
                NotificationLog.dedupe_key == dedupe_key,
            )
        )
    ).scalar_one_or_none()
    return row is not None and row > cutoff


async def _record(db: AsyncSession, org_id: uuid.UUID, dedupe_key: str, kind: AlertKind) -> None:
    """Stamp the fact as reported.

    Written *after* a successful send, not before: recording first would mean a
    Telegram outage silently consumes the alert, and the same fact is never
    mentioned again. Upsert rather than insert so an expired row is refreshed
    in place and two replicas racing on one tick cannot collide on the unique
    constraint.
    """
    now = datetime.now(timezone.utc)
    stmt = pg_insert(NotificationLog).values(
        id=uuid.uuid4(), org_id=org_id, dedupe_key=dedupe_key, kind=kind.value, sent_at=now
    )
    await db.execute(
        stmt.on_conflict_do_update(
            constraint="uq_notification_log_org_key",
            set_={"sent_at": now, "kind": kind.value},
        )
    )
    await db.commit()


async def prune_notification_log(db: AsyncSession, older_than_days: int = 30) -> int:
    """Delete dedupe rows past any plausible TTL.

    ``notification_log`` is append-mostly and nothing else ever removes a row;
    left alone it grows for the lifetime of the deployment. A row older than
    every TTL in use can no longer suppress anything, so dropping it is free.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, older_than_days))
    result = await db.execute(delete(NotificationLog).where(NotificationLog.sent_at < cutoff))
    await db.commit()
    return int(result.rowcount or 0)


# ── Delivery ─────────────────────────────────────────────────────────────


async def _deactivate(db: AsyncSession, account: TelegramAccount) -> None:
    """Stop writing to a chat Telegram says is gone for good.

    403 (bot blocked) and 400 (chat deleted) do not get better with retries,
    and a scheduler that keeps trying burns the bot's rate limit on a chat
    nobody reads. The row is kept so the panel can show "this link is dead"
    instead of quietly losing the owner.
    """
    account.is_active = False
    await db.commit()
    logger.warning(
        "owner_alert_chat_deactivated",
        account_id=str(account.id),
        org_id=str(account.org_id),
    )


async def _fan_out(
    db: AsyncSession,
    recipients: list[TelegramAccount],
    send: Callable[[str], Awaitable[SendResult]],
) -> int:
    """Send to every recipient, surviving each one's failure. Returns successes."""
    sent = 0
    for chat in recipients:
        try:
            result = await send(chat.chat_id or "")
        except Exception:  # noqa: BLE001 — one bad chat must not stop the rest.
            logger.exception("owner_alert_send_crashed", account_id=str(chat.id))
            continue
        if result.ok:
            sent += 1
        elif result.permanently_failed:
            await _deactivate(db, chat)
    return sent


async def _dispatch(
    db: AsyncSession,
    org_id: uuid.UUID,
    *,
    kind: AlertKind,
    severity: AlertSeverity,
    dedupe_key: str,
    dedupe_ttl_hours: int,
    send: Callable[[str], Awaitable[SendResult]],
) -> int:
    """Shared gate for both the text and the document path."""
    if not settings.telegram_configured:
        return 0

    chats = await _load_chats(db, org_id)
    if not chats:
        return 0  # nothing to suppress and nothing to record

    recipients, deferred = _split_recipients(chats, kind, severity)

    if not recipients:
        # Nobody is getting this. Record it anyway *unless* the only reason is
        # the hour — a fact everyone has muted is settled, a fact waiting for
        # morning is not.
        if not deferred and not await _already_reported(db, org_id, dedupe_key, dedupe_ttl_hours):
            await _record(db, org_id, dedupe_key, kind)
        return 0

    if await _already_reported(db, org_id, dedupe_key, dedupe_ttl_hours):
        return 0

    sent = await _fan_out(db, recipients, send)
    if sent:
        await _record(db, org_id, dedupe_key, kind)
    return sent


async def notify_owner(db: AsyncSession, org_id: uuid.UUID, alert: Alert) -> int:
    """Deliver ``alert`` to every activated owner chat in the org that wants it.

    Returns the number of chats messaged. Never raises: the caller is a
    scheduler job whose whole tick must survive a blocked bot or an unreachable
    Telegram.
    """
    text = render_alert(alert)

    async def _send(chat_id: str) -> SendResult:
        return await send_message(chat_id, text)

    try:
        return await _dispatch(
            db,
            org_id,
            kind=alert.kind,
            severity=alert.severity,
            dedupe_key=alert.dedupe_key,
            dedupe_ttl_hours=alert.dedupe_ttl_hours,
            send=_send,
        )
    except Exception:  # noqa: BLE001 — a broken alert must not kill the tick.
        logger.exception("notify_owner_failed", org_id=str(org_id), kind=alert.kind.value)
        try:
            await db.rollback()  # leave the caller a usable session
        except Exception:  # noqa: BLE001
            logger.exception("notify_owner_rollback_failed")
        return 0


async def _send_document(
    chat_id: str, filename: str, content: bytes, caption: str
) -> SendResult:
    """``sendDocument`` with the same never-raises contract as ``send_message``.

    Lives here rather than in ``app.services.telegram`` because it exists for
    this package: the report watchers hand an owner a finished .xlsx instead of
    a link they have to open a laptop to read.
    """
    if not settings.telegram_configured:
        return SendResult(ok=False, status_code=0)

    url = f"{_TELEGRAM_API}/bot{settings.telegram_bot_token}/sendDocument"
    try:
        async with httpx.AsyncClient(timeout=_DOCUMENT_TIMEOUT_S) as client:
            resp = await client.post(
                url,
                data={"chat_id": chat_id, "caption": caption[:1024], "parse_mode": "HTML"},
                files={"document": (filename, content)},
            )
    except httpx.HTTPError as exc:
        logger.warning("telegram_document_transport_error", chat_id=chat_id, error=str(exc))
        return SendResult(ok=False, status_code=0)

    if resp.status_code == 200:
        return SendResult(ok=True, status_code=200)
    logger.warning(
        "telegram_document_failed",
        chat_id=chat_id,
        status=resp.status_code,
        body=resp.text[:200],
    )
    return SendResult(
        ok=False, status_code=resp.status_code, permanently_failed=resp.status_code in (400, 403)
    )


async def send_owner_document(
    db: AsyncSession,
    org_id: uuid.UUID,
    *,
    filename: str,
    content: bytes,
    caption: str,
    dedupe_key: str,
    dedupe_ttl_hours: int = 24,
    kind: AlertKind = AlertKind.report_ready,
    # Above a new chat's conservative minimum on purpose: a document is never
    # spontaneous noise. A watcher only builds one because the owner's own
    # reporting schedule asked for it, so it should not be filtered out by the
    # setting that exists to suppress chatter.
    severity: AlertSeverity = AlertSeverity.warning,
) -> int:
    """Send a file to every owner chat that wants it, under the same gating.

    A monthly close is the motivating case: the owner should get the workbook
    itself, once, and not a fresh copy on every scheduler tick for the rest of
    the month.
    """

    async def _send(chat_id: str) -> SendResult:
        return await _send_document(chat_id, filename, content, caption)

    try:
        return await _dispatch(
            db,
            org_id,
            kind=kind,
            severity=severity,
            dedupe_key=dedupe_key,
            dedupe_ttl_hours=dedupe_ttl_hours,
            send=_send,
        )
    except Exception:  # noqa: BLE001
        logger.exception("send_owner_document_failed", org_id=str(org_id))
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            logger.exception("send_owner_document_rollback_failed")
        return 0
