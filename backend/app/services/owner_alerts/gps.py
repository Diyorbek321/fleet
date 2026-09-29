"""GPS watcher: a truck on a trip that has stopped reporting where it is.

Two signals, both only for trucks on a running trip. A truck parked in the yard
between loads is silent on purpose, and nobody needs to hear about it.

**Silent for a day.** No fix has arrived for ``GPS_SILENT_ALERT_HOURS``. The
server cannot tell a dead phone from a switched-off GPS or a driver who logged
out. All it sees is silence, so the dispatcher hears about it, and the driver
gets a push that will arrive whenever the phone comes back.

**Switched off on the phone.** The app reported location services off
(``trucks.gps_disabled_at``). The phone has already shown the driver its own
notification, so only the dispatcher is told. A short grace period stops a
driver toggling GPS for a minute from reaching the owner's chat.

Each is said once. The dedupe key includes the time of the last fix (or of the
switch-off), so the same silence is announced once and a new silence after the
truck came back gets its own message.
"""
from __future__ import annotations

import html
from datetime import datetime, timedelta, timezone

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import logger
from app.models.driver_messages import DriverMessageKind
from app.models.drivers import Driver
from app.models.enums import TripStatus
from app.models.trips import Trip
from app.models.trucks import Truck, TruckLocation
from app.services.driver_messages import send_driver_message
from app.services.owner_alerts.bus import Alert, AlertKind, AlertSeverity, notify_owner
from app.services.owner_alerts.trips import _headline, _humanize_lateness
from app.services.period_reports import report_tz

__all__ = ["run", "ACTIVE_TRIP_STATUSES"]

# A truck on one of these is "on a trip". Draft and planned have not left.
ACTIVE_TRIP_STATUSES = (TripStatus.loading, TripStatus.en_route, TripStatus.at_border)

# Past this, silence stops being news: a trip left "en route" for a month is a
# bookkeeping problem, and the dedupe log is pruned at 30 days, so a longer
# window would announce the same silence again.
MAX_SILENT_DAYS = 14

# Longer than the log's pruning age can matter, so "once" really is once.
DEDUPE_TTL_HOURS = 24 * 30

# Same reason as ``trips.MAX_ALERTS_PER_ORG``: the first tick after deploy finds
# the whole backlog. The rest are not recorded and go out on the next ticks.
MAX_ALERTS_PER_ORG = 5


def _esc(value: str) -> str:
    return html.escape(value, quote=False)


def _local(moment: datetime) -> str:
    return moment.astimezone(report_tz()).strftime("%d.%m %H:%M")


def _silent_key(row) -> str:
    return f"gps_silent:{row.truck_id}:{int(row.last_fix_at.timestamp())}"


def _disabled_key(row) -> str:
    return f"gps_disabled:{row.truck_id}:{int(row.gps_disabled_at.timestamp())}"


def _base_query() -> Select:
    """Trucks on a running trip, with their last fix and GPS switch state.

    Plain columns, not ORM entities: the bus and the message sender commit, and
    mapped instances held across a commit would lazy-load mid-tick.
    """
    return (
        select(
            Trip.id.label("trip_id"),
            Trip.org_id,
            Trip.reference,
            Trip.driver_id,
            Truck.id.label("truck_id"),
            Truck.plate_number,
            Truck.gps_disabled_at,
            Driver.name.label("driver_name"),
            TruckLocation.recorded_at.label("last_fix_at"),
        )
        .join(Truck, Truck.id == Trip.truck_id)
        .outerjoin(Driver, Driver.id == Trip.driver_id)
        .outerjoin(TruckLocation, TruckLocation.truck_id == Truck.id)
        .where(Trip.status.in_(ACTIVE_TRIP_STATUSES), Truck.is_enabled.is_(True))
    )


def silent_query(now: datetime, silent_after: timedelta) -> Select:
    return (
        _base_query()
        .where(
            TruckLocation.recorded_at < now - silent_after,
            TruckLocation.recorded_at >= now - timedelta(days=MAX_SILENT_DAYS),
        )
        .order_by(TruckLocation.recorded_at)
    )


def disabled_query(now: datetime, grace: timedelta) -> Select:
    return (
        _base_query()
        .where(
            Truck.gps_disabled_at.is_not(None),
            Truck.gps_disabled_at < now - grace,
            Truck.gps_disabled_at >= now - timedelta(days=MAX_SILENT_DAYS),
        )
        .order_by(Truck.gps_disabled_at)
    )


# ── Text ─────────────────────────────────────────────────────────────────
#
# Russian, like every other server-sent text (see app/services/push.py): the
# server does not know which language a driver picked in the app.


def driver_silent_text(plate: str) -> tuple[str, str]:
    return (
        "📡 Нет сигнала GPS",
        f"{plate}: ваш телефон не передаёт геолокацию больше суток. "
        "Откройте Fleet Watch и проверьте, что GPS включён.",
    )


def _silent_alert(row, now: datetime, driver_told: bool) -> Alert:
    body = [f"Последний сигнал: <b>{_esc(_local(row.last_fix_at))}</b>"]
    body.append(
        "Водителю отправлено уведомление в приложение."
        if driver_told
        else "Водитель не указан в рейсе — уведомить некого."
    )
    return Alert(
        kind=AlertKind.gps_signal,
        severity=AlertSeverity.warning,
        title=(
            f"{_headline(row.plate_number, row.driver_name, row.reference)}"
            f" — нет GPS {_humanize_lateness(now - row.last_fix_at)}"
        ),
        body="\n".join(body),
        dedupe_key=_silent_key(row),
        dedupe_ttl_hours=DEDUPE_TTL_HOURS,
        path=f"/trucks/{row.truck_id}",
    )


def _disabled_alert(row) -> Alert:
    return Alert(
        kind=AlertKind.gps_signal,
        severity=AlertSeverity.warning,
        title=(
            f"{_headline(row.plate_number, row.driver_name, row.reference)}"
            " — GPS выключен на телефоне"
        ),
        body=f"Выключен: <b>{_esc(_local(row.gps_disabled_at))}</b>",
        dedupe_key=_disabled_key(row),
        dedupe_ttl_hours=DEDUPE_TTL_HOURS,
        path=f"/trucks/{row.truck_id}",
    )


# ── Signals ──────────────────────────────────────────────────────────────


def _one_per_truck(rows) -> list:
    """A truck on two open trips is still one truck with one phone."""
    seen: set = set()
    unique = []
    for row in rows:
        if row.truck_id not in seen:
            seen.add(row.truck_id)
            unique.append(row)
    return unique


async def _report_silent(db: AsyncSession, now: datetime) -> int:
    hours = settings.gps_silent_alert_hours
    if hours <= 0:
        return 0
    rows = _one_per_truck((await db.execute(silent_query(now, timedelta(hours=hours)))).all())

    alerted: dict = {}
    for row in rows:
        driver_told = False
        if row.driver_id is not None:
            title, body = driver_silent_text(row.plate_number)
            # None when this silence was already announced — nothing new.
            await send_driver_message(
                db,
                org_id=row.org_id,
                driver_id=row.driver_id,
                truck_id=row.truck_id,
                kind=DriverMessageKind.gps_silent,
                title=title,
                body=body,
                dedupe_key=_silent_key(row),
            )
            driver_told = True

        if alerted.get(row.org_id, 0) >= MAX_ALERTS_PER_ORG:
            continue
        if await notify_owner(db, row.org_id, _silent_alert(row, now, driver_told)):
            alerted[row.org_id] = alerted.get(row.org_id, 0) + 1
    return sum(alerted.values())


async def _report_disabled(db: AsyncSession, now: datetime) -> int:
    grace = timedelta(minutes=settings.gps_disabled_grace_minutes)
    rows = _one_per_truck((await db.execute(disabled_query(now, grace))).all())

    alerted: dict = {}
    for row in rows:
        if alerted.get(row.org_id, 0) >= MAX_ALERTS_PER_ORG:
            continue
        if await notify_owner(db, row.org_id, _disabled_alert(row)):
            alerted[row.org_id] = alerted.get(row.org_id, 0) + 1
    return sum(alerted.values())


async def run(db: AsyncSession) -> int:
    """Evaluate both GPS signals across every organization. Never raises."""
    now = datetime.now(timezone.utc)
    sent = 0
    for signal in (_report_silent, _report_disabled):
        try:
            sent += await signal(db, now)
        except Exception:  # noqa: BLE001 — one broken signal must not hide the other.
            logger.exception("owner_alert_gps_signal_failed", signal=signal.__name__)
            try:
                await db.rollback()
            except Exception:  # noqa: BLE001
                logger.exception("owner_alert_gps_rollback_failed")
    logger.info("owner_alert_gps_done", sent=sent)
    return sent
