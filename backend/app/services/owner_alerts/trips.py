"""Trip watcher: a load running late, and a load that moved.

Two signals, found in deliberately different ways.

**Lateness is a state.** Nothing writes it down — a trip is late because its
``scheduled_end`` is in the past and its status still is not settled, which can
only be noticed by looking, and looking is what a fifteen-minute tick is for.
Severity follows how late the truck is and stops at ``warning`` on purpose:
``critical`` is the one level that punches through an owner's quiet hours, and a
truck that has been late since yesterday afternoon is not fixable at 03:00. That
message would only teach the owner to mute the bot.

**A status change is an event.** It is read back out of ``trip_events`` rather
than pushed from the code that advances a trip, for two reasons: the dispatcher
panel and the driver app both advance trips and only the timeline row is common
to both, and a watcher that reads is a watcher that can be added, fixed and
re-tuned without touching the request path that earns the money.

Both messages lead with the plate, then the driver, then the reference:

    01A123BC - Anvar - TR-2026-000042 Moskvaga 6 soat kechikdi

An owner knows their fleet as "Anvar's truck", not as TR-2026-000042; the
reference comes third, for whoever has to look the trip up afterwards.

Routine progress is ``info`` and lost revenue is ``warning``, so a chat left on
its quiet defaults hears about cancellations and late trucks and nothing else.
Owners who want the play-by-play turn their minimum down to ``info`` — that
knob is the entire reason severities exist.
"""
from __future__ import annotations

import html
from datetime import datetime, timedelta, timezone

from sqlalchemy import Select, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger
from app.models.drivers import Driver
from app.models.enums import TripStatus
from app.models.owner_alerts import NotificationLog
from app.models.trips import Trip, TripEvent
from app.models.trucks import Truck
from app.services.owner_alerts.bus import Alert, AlertKind, AlertSeverity, notify_owner
from app.services.period_reports import report_tz

# One Uzbek word per trip status, shared with the cargo-owner bot: the owner and
# their own customer must never read two different names for the same state.
from app.services.telegram import _status_label

__all__ = ["run"]


# An hour of slack before anything is said. Border queues, weighbridges and
# Tashkent traffic all cost an hour routinely; a fleet where every trip pings
# the owner at minute one is a fleet where nobody reads the pings.
LATE_GRACE_MINUTES = 60

# Below this a trip is merely behind schedule (``info``); above it, something
# has actually gone wrong (``warning``).
LATE_WARNING_HOURS = 3

# Past this, lateness stops being an operational fact and becomes a data-entry
# one: a trip abandoned in "planned" last spring is not news, and repeating it
# every day is exactly how an owner learns to ignore the bot.
LATE_MAX_DAYS = 30

# Wider than the tick interval on purpose. The bus defers a non-critical alert
# that lands inside an owner's quiet hours *without* recording it, so the event
# has to still be in the window when morning comes — a two-hour lookback would
# throw away everything that happened overnight.
STATUS_LOOKBACK_HOURS = 12

# Memory bound for one tick. Ordered oldest-first, so an overflow drops the
# newest events, which the next tick picks up; dropping the oldest would lose
# them for good as they age out of the window.
MAX_STATUS_EVENTS = 500

# A fact that is still true tomorrow is worth one line tomorrow, not ninety-six.
DEDUPE_TTL_HOURS = 24

# How many individual alerts one organization may receive from one signal in one
# tick. Lateness arrives in clusters — a border closing, a snowstorm, or simply
# the backlog of already-late trips on the first tick after an owner links their
# chat — and one message per truck would put twenty pings on a phone at once.
# That is the single fastest way to teach an owner to mute the bot, which
# silences every other alert kind along with it.
#
# The remainder is *not* recorded as sent, so the next tick picks it up: a
# backlog drains a capful at a time instead of arriving as a wall of text, and
# nothing is lost. Same contract as ``leakage.MAX_ALERTS_PER_ORG``.
MAX_ALERTS_PER_ORG = 5

# A trip in either of these has finished being anyone's problem.
SETTLED_STATUSES = (TripStatus.delivered, TripStatus.cancelled)

# Past-tense phrasing, not the state labels: this announces something that
# happened, so "yo'lga chiqdi" rather than "yo'lda". Statuses missing from this
# map (draft, planned, loading) are dispatcher bookkeeping — real work, but not
# the owner's phone at 14:20 on a Tuesday.
_TRANSITION_PHRASE: dict[TripStatus, str] = {
    TripStatus.en_route: "yo'lga chiqdi",
    TripStatus.at_border: "chegaraga yetdi",
    TripStatus.delivered: "yetkazildi",
    TripStatus.cancelled: "bekor qilindi",
}

_TRANSITION_SEVERITY: dict[TripStatus, AlertSeverity] = {
    TripStatus.en_route: AlertSeverity.info,
    TripStatus.at_border: AlertSeverity.info,
    TripStatus.delivered: AlertSeverity.info,
    # The only one that costs money rather than reporting it.
    TripStatus.cancelled: AlertSeverity.warning,
}

_NO_TRUCK = "mashinasiz"
_NO_DRIVER = "haydovchisiz"
_MAX_PLACE_CHARS = 40
_MAX_NOTE_CHARS = 200


# ── Text ─────────────────────────────────────────────────────────────────


def _esc(value: str) -> str:
    """Escape for the HTML body. ``quote=False`` for the same reason the bus
    uses it: half the Uzbek copy contains an apostrophe."""
    return html.escape(value, quote=False)


def _place(name: str | None) -> str | None:
    """The city out of a destination field.

    Dispatchers type anything from "Moskva" to a full street address; only the
    first comma-separated part belongs in a one-line title.
    """
    if not name:
        return None
    head = name.split(",")[0].strip()
    return head[:_MAX_PLACE_CHARS] or None


def _dative(place: str) -> str:
    """Uzbek dative: "Moskva" → "Moskvaga", "Chirchiq" → "Chirchiqqa".

    The suffix assimilates to the final consonant (-ka after k, -qa after q),
    and getting it wrong is the kind of small wrongness that makes a product
    read as foreign to the person paying for it.
    """
    tail = place[-1:].lower()
    if tail == "k":
        return place + "ka"
    if tail == "q":
        return place + "qa"
    return place + "ga"


def _humanize_lateness(late: timedelta) -> str:
    """How late, in the largest unit that is still honest. Floors rather than
    rounds: claiming seven hours when it is six and a half invites an argument
    with the driver about a number the owner did not need to be precise about.
    """
    minutes = max(0, int(late.total_seconds() // 60))
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    if days:
        return f"{days} kun {hours} soat" if hours else f"{days} kun"
    if hours:
        return f"{hours} soat"
    return f"{minutes} daqiqa"


def _local(moment: datetime) -> str:
    return moment.astimezone(report_tz()).strftime("%d.%m %H:%M")


def _headline(plate: str | None, driver: str | None, reference: str) -> str:
    return f"{plate or _NO_TRUCK} - {driver or _NO_DRIVER} - {reference}"


def _route_line(origin: str | None, destination: str | None) -> str | None:
    """"Toshkent → Moskva", or whichever half is known."""
    start, end = _place(origin), _place(destination)
    if start and end:
        route = f"{_esc(start)} → {_esc(end)}"
    elif start or end:
        route = _esc(start or end or "")
    else:
        return None
    return f"Yo'nalish: <b>{route}</b>"


def _severity_for_lateness(late: timedelta) -> AlertSeverity:
    """Never ``critical``. See the module docstring: nothing about a late truck
    justifies waking its owner at 03:00, and the bus lets ``critical`` through
    quiet hours."""
    if late >= timedelta(hours=LATE_WARNING_HOURS):
        return AlertSeverity.warning
    return AlertSeverity.info


# ── Queries ──────────────────────────────────────────────────────────────
#
# Both select plain columns rather than ORM entities: the bus commits after
# every send, and a loop that holds mapped instances across a commit is one
# session setting away from lazy-loading in the middle of a scheduler tick.


def _late_trip_query(now: datetime) -> Select:
    return (
        select(
            Trip.id,
            Trip.org_id,
            Trip.reference,
            Trip.status,
            Trip.scheduled_end,
            Trip.origin_name,
            Trip.destination_name,
            Truck.plate_number,
            Driver.name.label("driver_name"),
        )
        .outerjoin(Truck, Truck.id == Trip.truck_id)
        .outerjoin(Driver, Driver.id == Trip.driver_id)
        .where(
            Trip.scheduled_end.is_not(None),
            Trip.scheduled_end < now - timedelta(minutes=LATE_GRACE_MINUTES),
            Trip.scheduled_end >= now - timedelta(days=LATE_MAX_DAYS),
            Trip.status.not_in(SETTLED_STATUSES),
        )
        .order_by(Trip.scheduled_end)
    )


def _status_event_query(cutoff: datetime) -> Select:
    return (
        select(
            TripEvent.to_status,
            TripEvent.recorded_at,
            TripEvent.note,
            Trip.id.label("trip_id"),
            Trip.org_id,
            Trip.reference,
            Trip.origin_name,
            Trip.destination_name,
            Truck.plate_number,
            Driver.name.label("driver_name"),
        )
        .join(Trip, Trip.id == TripEvent.trip_id)
        .outerjoin(Truck, Truck.id == Trip.truck_id)
        .outerjoin(Driver, Driver.id == Trip.driver_id)
        .where(
            TripEvent.recorded_at >= cutoff,
            TripEvent.to_status.in_(tuple(_TRANSITION_PHRASE)),
            # A dispatcher re-saving the same status writes a timeline row that
            # moved nothing. The trip created straight into a status has no
            # from_status at all and is genuine news.
            or_(
                TripEvent.from_status.is_(None),
                TripEvent.from_status != TripEvent.to_status,
            ),
        )
        .order_by(TripEvent.recorded_at)
        .limit(MAX_STATUS_EVENTS)
    )


# ── Volume control ───────────────────────────────────────────────────────
#
# The dedupe keys live here, as one definition each, because two places now
# derive them: the pre-filter that decides what is still owed a message, and
# the send itself. Two spellings of the same key would silently disagree about
# what has already been reported.


def _late_key(row, now: datetime) -> str:
    """The severity belongs in the key: the owner hears once when a truck starts
    running late, once more when it stops being a rounding error, and — through
    the daily TTL — once a day for as long as it stays that way."""
    return f"trip_delay:{row.id}:{_severity_for_lateness(now - row.scheduled_end).value}"


def _status_key(row) -> str:
    """Keyed on the fact ("this trip reached delivered"), not on the timeline
    row: a dispatcher who advances, reverts and advances again produces two rows
    and one piece of news."""
    return f"trip_status:{row.trip_id}:{row.to_status.value}"



def _by_org(rows) -> dict:
    """Group query rows by organization, preserving the query's own ordering.

    The cap has to be per organization, not per tick: capping globally would let
    one busy fleet's backlog crowd out every other customer's alerts entirely.
    """
    grouped: dict = {}
    for row in rows:
        grouped.setdefault(row.org_id, []).append(row)
    return grouped


async def _unreported(db: AsyncSession, org_id, keys: list[str]) -> set[str]:
    """Which of ``keys`` this org has not been told about inside the TTL.

    The bus checks this again per alert and remains the authority; this pass
    exists because the cap has to rank *new* facts. Slicing the raw query
    instead spends every slot re-suppressing trips already reported, and the
    ones still owed a message sit permanently behind them — a backlog that
    never drains, which is strictly worse than no cap at all.
    """
    if not keys:
        return set()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=DEDUPE_TTL_HOURS)
    seen = set(
        (
            await db.execute(
                select(NotificationLog.dedupe_key).where(
                    NotificationLog.org_id == org_id,
                    NotificationLog.dedupe_key.in_(keys),
                    NotificationLog.sent_at > cutoff,
                )
            )
        ).scalars().all()
    )
    return {key for key in keys if key not in seen}


def _today_key() -> str:
    """Local calendar day, for deduping a roll-up to one line a day.

    The owner needs to know a backlog exists once, not on every tick while it
    drains — and the backlog is a fact about today, so the day is the key.
    """
    return datetime.now(report_tz()).strftime("%Y-%m-%d")


def _remainder_alert(kind: AlertKind, count: int, today: str) -> Alert:
    """One line standing in for everything the cap held back."""
    noun = "kechikkan reys" if kind is AlertKind.trip_delay else "reys yangiligi"
    return Alert(
        kind=kind,
        severity=AlertSeverity.info,
        title=f"Yana {count} ta {noun} bor",
        body=(
            "Ro'yxat uzun bo'lgani uchun qolgani keyingi tekshiruvda yuboriladi.\n"
            "Hammasini panelda ko'rish mumkin."
        ),
        dedupe_key=f"{kind.value}:overflow:{today}",
        dedupe_ttl_hours=DEDUPE_TTL_HOURS,
        path="/trips",
    )


# ── Signals ──────────────────────────────────────────────────────────────


async def _report_late_trips(db: AsyncSession) -> int:
    now = datetime.now(timezone.utc)
    all_rows = (await db.execute(_late_trip_query(now))).all()

    sent = 0
    today = _today_key()
    for org_id, org_rows in _by_org(all_rows).items():
        keyed = [(_late_key(row, now), row) for row in org_rows]
        fresh_keys = await _unreported(db, org_id, [key for key, _row in keyed])
        pending = [row for key, row in keyed if key in fresh_keys]

        # Ordered by scheduled_end ascending, so the head of the list is the
        # truck that has been late longest — the one worth the owner's first
        # message when only a few get through.
        capped = pending[:MAX_ALERTS_PER_ORG]
        overflow = len(pending) - len(capped)
        sent += await _send_late_batch(db, capped, now)
        if overflow:
            sent += await notify_owner(
                db, org_id, _remainder_alert(AlertKind.trip_delay, overflow, today)
            )
    return sent


async def _send_late_batch(db: AsyncSession, rows, now: datetime) -> int:
    sent = 0
    for row in rows:
        late = now - row.scheduled_end
        severity = _severity_for_lateness(late)

        destination = _place(row.destination_name)
        where = f"{_dative(destination)} " if destination else ""
        body = [
            f"Reja: <b>{_esc(_local(row.scheduled_end))}</b>",
            f"Holati: <b>{_esc(_status_label(row.status))}</b>",
        ]
        route = _route_line(row.origin_name, row.destination_name)
        if route:
            body.append(route)

        sent += await notify_owner(
            db,
            row.org_id,
            Alert(
                kind=AlertKind.trip_delay,
                severity=severity,
                title=(
                    f"{_headline(row.plate_number, row.driver_name, row.reference)} "
                    f"{where}{_humanize_lateness(late)} kechikdi"
                ),
                body="\n".join(body),
                dedupe_key=_late_key(row, now),
                dedupe_ttl_hours=DEDUPE_TTL_HOURS,
                path=f"/trips/{row.id}",
            ),
        )
    return sent


async def _report_status_changes(db: AsyncSession) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=STATUS_LOOKBACK_HOURS)
    all_rows = (await db.execute(_status_event_query(cutoff))).all()

    sent = 0
    today = _today_key()
    for org_id, org_rows in _by_org(all_rows).items():
        keyed = [(_status_key(row), row) for row in org_rows]
        fresh_keys = await _unreported(db, org_id, [key for key, _row in keyed])
        pending = [row for key, row in keyed if key in fresh_keys]

        # Oldest first, matching the query: a timeline is read forwards, and an
        # owner catching up wants the departure before the border crossing.
        capped = pending[:MAX_ALERTS_PER_ORG]
        overflow = len(pending) - len(capped)
        sent += await _send_status_batch(db, capped)
        if overflow:
            sent += await notify_owner(
                db, org_id, _remainder_alert(AlertKind.trip_status, overflow, today)
            )
    return sent


async def _send_status_batch(db: AsyncSession, rows) -> int:
    sent = 0
    for row in rows:
        phrase = _TRANSITION_PHRASE[row.to_status]

        body = []
        route = _route_line(row.origin_name, row.destination_name)
        if route:
            body.append(route)
        body.append(f"Vaqt: <b>{_esc(_local(row.recorded_at))}</b>")
        if row.note:
            body.append(f"Izoh: {_esc(row.note[:_MAX_NOTE_CHARS])}")

        sent += await notify_owner(
            db,
            row.org_id,
            Alert(
                kind=AlertKind.trip_status,
                severity=_TRANSITION_SEVERITY[row.to_status],
                title=f"{_headline(row.plate_number, row.driver_name, row.reference)} {phrase}",
                body="\n".join(body),
                dedupe_key=_status_key(row),
                dedupe_ttl_hours=DEDUPE_TTL_HOURS,
                path=f"/trips/{row.trip_id}",
            ),
        )
    return sent


async def run(db: AsyncSession) -> int:
    """Evaluate both trip signals across every organization and notify.

    Returns the number of chats messaged. Never raises, and a signal that fails
    does not take the other one with it — a scheduler tick is the only chance
    either of them gets for the next fifteen minutes.
    """
    sent = 0
    for signal in (_report_late_trips, _report_status_changes):
        try:
            sent += await signal(db)
        except Exception:  # noqa: BLE001 — one broken query must not hide the other signal.
            logger.exception("owner_alert_trip_signal_failed", signal=signal.__name__)
            try:
                await db.rollback()  # leave the next signal a usable session
            except Exception:  # noqa: BLE001
                logger.exception("owner_alert_trip_rollback_failed")
    logger.info("owner_alert_trips_done", sent=sent)
    return sent
