"""Keep reminding until the phone reports.

The trip watcher (``owner_alerts/gps.py``) says each silence once, and only for
trucks on a trip. A driver who never switched sharing on, told once or never,
simply stays off the map. So:

* **The driver** of every truck that is not reporting gets a push and an inbox
  message every ``GPS_REMINDER_HOURS``, worded for the reason, until a position
  arrives. Any GPS message they got inside that window — this one or the trip
  watcher's — counts, so the two never stack.
* **The dispatcher** gets one list a day of every truck still not reporting,
  with why. A driver who never signed in has no phone we can reach; that list
  is how someone gets told to call them.
"""
from __future__ import annotations

import html
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import logger
from app.models.driver_messages import DriverMessage, DriverMessageKind
from app.models.trucks import Truck
from app.services.driver_messages import send_driver_message
from app.services.owner_alerts.bus import Alert, AlertKind, AlertSeverity, notify_owner
from app.services.owner_alerts.gps import driver_never_text, driver_silent_text
from app.services.period_reports import report_tz
from app.services.truck_signal import SignalState, TruckSignal, fleet_signal

__all__ = ["run"]

# Long enough that tomorrow's list is a new key; short enough to be pruned.
DIGEST_TTL_HOURS = 48

# Russian, like every other server-sent text: the server does not know which
# language a driver picked, and the owner chats are Russian throughout.
_REASON = {
    SignalState.no_driver: "водитель не назначен",
    SignalState.gps_off: "GPS выключен на телефоне",
    SignalState.never: "ни разу не подключался",
    SignalState.silent: "сигнал пропал",
}


def _driver_gps_off_text(plate: str) -> tuple[str, str]:
    return (
        "📡 GPS выключен",
        f"{plate}: на телефоне выключена геолокация. Включите GPS — диспетчер не видит машину.",
    )


def _driver_text(signal: TruckSignal, now: datetime) -> tuple[str, str]:
    if signal.state is SignalState.gps_off:
        return _driver_gps_off_text(signal.plate_number)
    if signal.state is SignalState.silent and signal.last_fix_at is not None:
        return driver_silent_text(signal.plate_number, now - signal.last_fix_at)
    return driver_never_text(signal.plate_number)


async def _told_recently(db: AsyncSession, driver_id: uuid.UUID, since: datetime) -> bool:
    newest = await db.scalar(
        select(func.max(DriverMessage.created_at)).where(
            DriverMessage.driver_id == driver_id,
            DriverMessage.kind == DriverMessageKind.gps_silent.value,
        )
    )
    return newest is not None and newest > since


async def _remind_drivers(
    db: AsyncSession, org_id: uuid.UUID, problems: list[TruckSignal], now: datetime, every: timedelta
) -> int:
    sent = 0
    for signal in problems:
        if signal.driver_id is None or await _told_recently(db, signal.driver_id, now - every):
            continue
        title, body = _driver_text(signal, now)
        # The window check above is what spaces reminders out; the key only
        # has to be unique, since every reminder is meant to land.
        message = await send_driver_message(
            db,
            org_id=org_id,
            driver_id=signal.driver_id,
            truck_id=signal.truck_id,
            kind=DriverMessageKind.gps_silent,
            title=title,
            body=body,
            dedupe_key=f"gps_remind:{signal.truck_id}:{uuid.uuid4().hex}",
        )
        sent += message is not None
    return sent


def _digest_line(signal: TruckSignal) -> str:
    parts = [f"<b>{html.escape(signal.plate_number, quote=False)}</b>"]
    if signal.driver_name:
        parts.append(html.escape(signal.driver_name, quote=False))
    if signal.driver_phone:
        parts.append(html.escape(signal.driver_phone, quote=False))
    parts.append(_REASON[signal.state])
    return "• " + " — ".join(parts)


def _digest(org_id: uuid.UUID, problems: list[TruckSignal], now: datetime) -> Alert:
    day = now.astimezone(report_tz()).date().isoformat()
    return Alert(
        kind=AlertKind.gps_signal,
        severity=AlertSeverity.warning,
        title=f"Без сигнала GPS: {len(problems)} машин",
        body="\n".join(_digest_line(s) for s in problems),
        dedupe_key=f"gps_digest:{org_id}:{day}",
        dedupe_ttl_hours=DIGEST_TTL_HOURS,
        path="/map",
    )


async def _org_ids(db: AsyncSession) -> list[uuid.UUID]:
    rows = await db.execute(select(Truck.org_id).where(Truck.is_enabled.is_(True)).distinct())
    return list(rows.scalars().all())


async def run(db: AsyncSession) -> int:
    """Remind drivers and send the daily list. Returns messages sent. Never raises."""
    hours = settings.gps_reminder_hours
    if hours <= 0:
        return 0
    now = datetime.now(timezone.utc)
    every = timedelta(hours=hours)
    stale = timedelta(minutes=settings.gps_stale_after_minutes)

    sent = 0
    for org_id in await _org_ids(db):
        try:
            signals = await fleet_signal(db, org_id, stale, now=now)
            problems = [s for s in signals if s.state is not SignalState.ok]
            if not problems:
                continue
            sent += await _remind_drivers(db, org_id, problems, now, every)
            sent += await notify_owner(db, org_id, _digest(org_id, problems, now))
        except Exception:  # noqa: BLE001 — one fleet must not stop the others.
            logger.exception("signal_reminders_org_failed", org_id=str(org_id))
            await db.rollback()
    logger.info("signal_reminders_done", sent=sent)
    return sent
