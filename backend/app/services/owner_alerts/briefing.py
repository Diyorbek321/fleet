"""Ertalabki xulosa — five Uzbek lines telling an owner what the fleet did overnight.

The owner of a mid-size fleet does not open a dashboard at 07:00. They open
Telegram. So this watcher is the one alert that fires whether or not anything
went wrong: it is the daily proof that the system is watching, and the habit
that makes every other alert legible when it does arrive.

Two decisions carry the whole module.

**The numbers are computed here; the model only phrases them.** Everything the
digest states comes out of :func:`collect` as a :class:`Figure` with a value and
a pre-formatted string, and the same list feeds both the prompt and
:func:`unverified_numbers`. Any digit in the model's answer that is not one of
those values throws the whole answer away and the templated digest goes out
instead. A fabricated litre count in a money report does not cost us one wrong
message — it costs us the owner's belief in every number the product has ever
shown them, and there is no way to earn that back.

**No key means plainer prose, never silence.** ``settings.ai_api_key`` is empty
by default and most deployments will never set it. The templated path is
therefore the normal path, not a degraded one: it states the same figures in the
same five lines, just without the connective tissue.

Scope and window:

* The day summarised is yesterday in **local** (Asia/Tashkent) terms, so "kecha"
  means the day the owner means. A UTC day would file the first five hours of
  every morning under the wrong date.
* One GPS scan per organization covers that day, and
  :func:`~app.services.analytics.unauthorized_stops` is fed from it rather than
  scanning again. The one leakage figure deliberately *not* reported is
  fuel-waste-vs-baseline: litres bought in a single day is not litres burned in
  it (see ``PeriodReport.consumption_reliable``), and a made-up efficiency
  number in a trust-building message is exactly the wrong trade.
* Only organizations with a live chat *and* an unsuspended account are visited,
  which keeps the scan off orgs nobody is listening to and stops a customer who
  has been locked out of the panel from still receiving their morning numbers.
"""
from __future__ import annotations

import asyncio
import html
import os
import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import logger
from app.models.driver_app import DriverExpense
from app.models.drivers import Driver
from app.models.enums import ServiceStatus, TripStatus
from app.models.maintenance import FuelLog
from app.models.organizations import Organization
from app.models.owner_alerts import TelegramAccount
from app.models.trips import Trip
from app.models.trucks import Truck
from app.services.ai_reports import LANGUAGE_NAMES
from app.services.ai_reports import _call_ai as call_chat_completion
from app.services.analytics import scan_tracks, unauthorized_stops
from app.services.owner_alerts.bus import Alert, AlertKind, AlertSeverity, notify_owner
from app.services.period_reports import report_tz
from app.services.reminders import upcoming_expiries

__all__ = [
    "BriefingFacts",
    "Figure",
    "briefing_hour",
    "build_alert",
    "build_prompt",
    "collect",
    "compose_with_ai",
    "render_plain",
    "run",
    "unverified_numbers",
]

# 07:00 Tashkent: after the owner is awake, before the first dispatch call.
DEFAULT_BRIEFING_HOUR = 7

# The digest may be delivered any time inside this many hours after the target
# hour. Not cosmetic: a chat whose quiet window has not ended yet is *deferred*
# by the bus without recording the fact, and a gate that only fired on one exact
# hour would then drop that owner's briefing for the day entirely. It also means
# a worker restarted at 07:20 still delivers the morning digest. Dedupe on
# ``briefing:<date>`` is what keeps "any tick in the window" to one message.
BRIEFING_CATCHUP_HOURS = 6

# Documents and services this close to lapsing are worth a line in a *daily*
# digest; the 30-day view belongs on the dashboard, not in the owner's pocket.
EXPIRY_HORIZON_DAYS = 7

# Shorter than ai_reports' own 90s: this runs inside a scheduler tick shared
# with every other watcher, and a hung provider must not hold it open.
AI_TIMEOUT_S = 45.0

# A model that answers with one line has not written a digest. Below this we
# take the template rather than send something that looks truncated.
MIN_AI_LINES = 3

# Trips that are actually on the road. ``planned`` is excluded on purpose: a
# load that has not been picked up yet is not something the owner can act on
# over breakfast, and counting it inflates the only figure in the digest an
# owner can check by looking out of the window.
_ON_THE_ROAD = (TripStatus.loading, TripStatus.en_route, TripStatus.at_border)


# ── Figures ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Figure:
    """One number, its Uzbek label, and the exact text the owner will read.

    ``key`` is ASCII so the template can address a figure without embedding
    Uzbek apostrophes in its own source; ``label`` is what the model is shown.

    ``value`` is the number *as displayed*, not the raw one — the verifier
    compares the model's digits against what it was shown, so a figure rounded
    for display has to be allowed at that precision or honest prose would be
    rejected for quoting it correctly.
    """

    key: str
    label: str
    text: str
    value: float


def _group(value: int) -> str:
    """Thousands separated by spaces, the way an Uzbek invoice is written."""
    return f"{value:,}".replace(",", " ")


def _count(key: str, label: str, value: int) -> Figure:
    return Figure(key=key, label=label, text=f"{_group(int(value))} ta", value=float(int(value)))


def _money(key: str, label: str, value: float) -> Figure:
    # UZS across the board, matching ``PeriodReport.currency``: trips carry a
    # per-trip currency code for cross-border loads, but every money total in
    # this product is already stated in so'm and inventing a second convention
    # here would make two screens disagree.
    rounded = round(float(value))
    return Figure(key=key, label=label, text=f"{_group(rounded)} so'm", value=float(rounded))


def _distance(key: str, label: str, value: float) -> Figure:
    rounded = round(float(value))
    return Figure(key=key, label=label, text=f"{_group(rounded)} km", value=float(rounded))


def _liters(key: str, label: str, value: float) -> Figure:
    rounded = round(float(value))
    return Figure(key=key, label=label, text=f"{_group(rounded)} l", value=float(rounded))


def _hours(key: str, label: str, value: float) -> Figure:
    rounded = round(float(value), 1)
    return Figure(key=key, label=label, text=f"{rounded:.1f} soat", value=rounded)


# ── Facts ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class BriefingFacts:
    """Everything the digest may state about one organization's yesterday."""

    org_id: uuid.UUID
    org_name: str
    day: date

    delivered_trips: int = 0
    delivered_revenue: float = 0.0
    on_the_road: int = 0
    distance_km: float = 0.0
    fuel_liters: float = 0.0
    fuel_cost: float = 0.0
    expense_cost: float = 0.0
    unauthorized_stops: int = 0
    idle_hours: float = 0.0
    overdue_items: int = 0
    expiring_soon: int = 0

    def figures(self) -> list[Figure]:
        """The single source of truth for both the prompt and the verifier.

        Building the prompt from one list and the allow-list from another is how
        a figure ends up quotable-but-unverified; there is only one list.
        """
        return [
            _count("delivered", "kecha yetkazilgan reyslar", self.delivered_trips),
            _money("revenue", "kecha tushgan daromad", self.delivered_revenue),
            _count("on_road", "hozir yo'ldagi mashinalar", self.on_the_road),
            _distance("distance", "kecha bosib o'tilgan yo'l", self.distance_km),
            _liters("liters", "kecha quyilgan yoqilg'i", self.fuel_liters),
            _money("fuel_cost", "yoqilg'i uchun to'langan pul", self.fuel_cost),
            _money("expenses", "haydovchilarning kecha qilgan xarajati", self.expense_cost),
            _count("stops", "ruxsatsiz to'xtashlar", self.unauthorized_stops),
            _hours("idle", "bekor turgan vaqt", self.idle_hours),
            _count("overdue", "muddati o'tgan hujjat va texnik xizmatlar", self.overdue_items),
            _count("soon", "muddati yaqinlashayotganlar", self.expiring_soon),
        ]


def _day_bounds_utc(day: date) -> tuple[datetime, datetime]:
    """Half-open UTC bounds of one local calendar day.

    The end is midnight *after* the day, so a fill stamped 23:59 belongs to the
    day it happened on — the same reasoning as ``Period.bounds_utc``.
    """
    tz = report_tz()
    start = datetime.combine(day, time.min, tzinfo=tz)
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=tz)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


async def collect(db: AsyncSession, org_id: uuid.UUID, day: date) -> BriefingFacts:
    """Measure one organization's ``day``. Every figure in the digest is born here."""
    start_utc, end_utc = _day_bounds_utc(day)

    org_name = (
        await db.execute(select(Organization.name).where(Organization.id == org_id))
    ).scalar() or ""

    delivered_count, delivered_revenue = (
        await db.execute(
            select(func.count(Trip.id), func.coalesce(func.sum(Trip.rate), 0)).where(
                Trip.org_id == org_id,
                Trip.status == TripStatus.delivered,
                Trip.delivered_at >= start_utc,
                Trip.delivered_at < end_utc,
            )
        )
    ).one()

    on_the_road = (
        await db.execute(
            select(func.count(Trip.id)).where(
                Trip.org_id == org_id, Trip.status.in_(_ON_THE_ROAD)
            )
        )
    ).scalar() or 0

    fuel_liters, fuel_cost = (
        await db.execute(
            select(
                func.coalesce(func.sum(FuelLog.liters), 0),
                func.coalesce(func.sum(FuelLog.total_cost), 0),
            )
            .join(Truck, Truck.id == FuelLog.truck_id)
            .where(Truck.org_id == org_id, FuelLog.filled_at >= start_utc, FuelLog.filled_at < end_utc)
        )
    ).one()

    expense_cost = (
        await db.execute(
            select(func.coalesce(func.sum(DriverExpense.amount), 0))
            .join(Driver, Driver.id == DriverExpense.driver_id)
            .where(Driver.org_id == org_id, DriverExpense.spent_at == day)
        )
    ).scalar() or 0

    # One scan, two answers: the distance total and the stops. Passing ``tracks``
    # in is what stops this from being a second full pass over the same rows.
    tracks = await scan_tracks(db, start_utc, end_utc, org_id)
    distance_km = sum(track.distance_km for track in tracks.values())
    stops = await unauthorized_stops(db, 1, org_id, tracks=tracks)

    expiries = await upcoming_expiries(db, org_id, days_ahead=EXPIRY_HORIZON_DAYS)
    overdue = sum(1 for row in expiries["license_expiries"] if row["expired"])
    overdue += sum(
        1 for row in expiries["service_due"] if row["status"] == ServiceStatus.overdue.value
    )

    return BriefingFacts(
        org_id=org_id,
        org_name=org_name,
        day=day,
        delivered_trips=int(delivered_count or 0),
        delivered_revenue=float(delivered_revenue or 0),
        on_the_road=int(on_the_road),
        distance_km=float(distance_km),
        fuel_liters=float(fuel_liters or 0),
        fuel_cost=float(fuel_cost or 0),
        expense_cost=float(expense_cost or 0),
        unauthorized_stops=int(stops["unauthorized_stop_count"]),
        idle_hours=float(stops["total_idle_hours"]),
        overdue_items=overdue,
        expiring_soon=max(int(expiries["total"]) - overdue, 0),
    )


# ── The templated digest ─────────────────────────────────────────────────


def render_plain(facts: BriefingFacts) -> list[str]:
    """Five HTML lines stating the figures, with no model involved.

    This is what ships when no API key is configured, and what ships when the
    model's answer fails verification. Zeros are printed rather than hidden: an
    owner needs "kecha 0 ta reys yetkazildi" to read as a fact about the fleet,
    not as a line the digest forgot.
    """
    t = {figure.key: f"<b>{figure.text}</b>" for figure in facts.figures()}
    return [
        f"🚚 Reyslar — kecha {t['delivered']} yetkazildi, daromad {t['revenue']}. "
        f"Hozir yo'lda {t['on_road']} mashina bor.",
        f"🛣 Yo'l — kecha {t['distance']} bosib o'tildi.",
        f"⛽ Yoqilg'i — {t['liters']} quyildi, {t['fuel_cost']} to'landi.",
        f"💵 Xarajat — haydovchilar kecha {t['expenses']} sarfladi.",
        f"⚠️ Diqqat — {t['stops']} ruxsatsiz to'xtash ({t['idle']} bekor turish), "
        f"{t['overdue']} hujjat/xizmat muddati o'tgan, {t['soon']} muddati yaqinlashmoqda.",
    ]


# ── The model's half ─────────────────────────────────────────────────────


def build_prompt(facts: BriefingFacts) -> tuple[str, str]:
    """System + user messages for the digest.

    The organization's name is deliberately absent. A fleet called "Fleet 24"
    would put a stray ``24`` in the prose, and the verifier — correctly — cannot
    tell that digit apart from an invented litre count.
    """
    lang = LANGUAGE_NAMES["uz"]
    system = (
        f"You write a five-line morning briefing for the owner of an Uzbek trucking "
        f"company. Write entirely in {lang}, in short plain sentences an owner reads "
        f"in fifteen seconds.\n"
        "Rules that override everything else:\n"
        "- Use ONLY the numbers listed below. Copy each one exactly as written, "
        "digit for digit and space for space, together with its unit.\n"
        "- Never calculate, round, convert, compare or estimate a number, and never "
        "write a number that is not in the list — no dates, no percentages, no totals "
        "of your own.\n"
        "- Exactly five lines, one sentence each, no markdown, no headings, no bullet "
        "characters."
    )
    lines = "\n".join(f"- {figure.label}: {figure.text}" for figure in facts.figures())
    user = f"Kechagi kun raqamlari:\n{lines}"
    return system, user


# Matches a number the way a person writes one: optional groups of exactly three
# digits after a space/dot/comma, then an optional 1-2 digit decimal part. Kept
# tight on purpose — "2, 3 va 4" must read as three separate numbers, not one.
_NUMBER_RE = re.compile(r"\d+(?:[ \u00a0.,]\d{3})*(?:[.,]\d{1,2})?")


def _to_number(raw: str) -> float | None:
    """Parse one written number, or ``None`` when its shape is ambiguous.

    A separator followed by exactly three digits is thousands grouping; one
    followed by one or two digits is a decimal mark. Anything that fits neither
    reading is rejected rather than guessed — an unparseable number is treated
    as unverifiable, which is the safe direction.
    """
    text = re.sub(r"\s", "", raw)
    match = re.fullmatch(r"(\d+(?:[.,]\d{3})*)(?:([.,])(\d{1,2}))?", text)
    if match is None:
        return None
    whole = re.sub(r"[.,]", "", match.group(1))
    fraction = match.group(3)
    return float(f"{whole}.{fraction}") if fraction else float(whole)


def unverified_numbers(text: str, figures: list[Figure]) -> list[str]:
    """Every number in ``text`` that was not one of ``figures``.

    The gate the whole feature rests on. It is deliberately unforgiving: a model
    that helpfully totals two of our figures produces a number we never measured,
    and a digest that quietly mixes measured and derived numbers is worse than
    one with no prose at all.
    """
    allowed = [figure.value for figure in figures]
    bad: list[str] = []
    for raw in _NUMBER_RE.findall(text):
        value = _to_number(raw)
        if value is None or not any(abs(value - candidate) < 1e-6 for candidate in allowed):
            bad.append(raw)
    return bad


async def compose_with_ai(facts: BriefingFacts) -> list[str] | None:
    """Ask the model to phrase ``facts``. ``None`` means "use the template".

    Returns escaped HTML lines. Never raises and never lets the caller wait on a
    stalled provider: every exit that is not a verified answer is a ``None``.
    """
    if not settings.ai_api_key:
        return None

    system, user = build_prompt(facts)
    try:
        answer = await asyncio.wait_for(call_chat_completion(system, user), timeout=AI_TIMEOUT_S)
    except Exception as exc:  # noqa: BLE001 — a provider outage costs prose, not the digest.
        logger.warning("briefing_ai_call_failed", org_id=str(facts.org_id), error=str(exc))
        return None

    lines = [line.strip() for line in (answer or "").splitlines() if line.strip()]
    if len(lines) < MIN_AI_LINES:
        logger.warning("briefing_ai_answer_too_short", org_id=str(facts.org_id), lines=len(lines))
        return None

    invented = unverified_numbers("\n".join(lines), facts.figures())
    if invented:
        logger.warning(
            "briefing_ai_invented_numbers", org_id=str(facts.org_id), numbers=invented[:5]
        )
        return None

    # The model's text is data, not markup: escape it. Apostrophes are left
    # alone for the same reason ``render_alert`` leaves them alone — half the
    # Uzbek vocabulary in this digest contains one.
    return [html.escape(line, quote=False) for line in lines[:5]]


# ── Scheduling ───────────────────────────────────────────────────────────


def briefing_hour() -> int:
    """Local (Asia/Tashkent) hour the digest targets.

    Read from ``settings`` when the deployment has grown a field for it, else
    from ``BRIEFING_HOUR_LOCAL``, else 07:00. Out-of-range values fall back
    rather than raise: a typo in a settings form must not silence the digest,
    and it must not crash the tick either.
    """
    raw = getattr(settings, "briefing_hour_local", None)
    if raw is None:
        raw = os.environ.get("BRIEFING_HOUR_LOCAL", "")
    try:
        hour = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_BRIEFING_HOUR
    return hour if 0 <= hour <= 23 else DEFAULT_BRIEFING_HOUR


def _in_window(now_local: datetime) -> bool:
    """Whether the digest may go out now.

    Deliberately does not wrap past midnight: the window's whole job is to keep
    "yesterday" meaning one fixed day for as long as it is open, and a window
    that crossed midnight would change that day underneath itself.
    """
    target = briefing_hour()
    return target <= now_local.hour < target + BRIEFING_CATCHUP_HOURS


async def _listening_org_ids(db: AsyncSession) -> list[uuid.UUID]:
    """Organizations with a live chat and an account that is not suspended.

    Filtering here rather than inside the loop is what keeps a GPS scan off
    every org that would only have its digest dropped by the bus anyway. The
    ``is_active`` join is the billing boundary: a customer locked out of the
    panel for an unpaid invoice should not still be getting their numbers.
    """
    rows = (
        await db.execute(
            select(TelegramAccount.org_id)
            .join(Organization, Organization.id == TelegramAccount.org_id)
            .where(
                TelegramAccount.is_active.is_(True),
                TelegramAccount.chat_id.is_not(None),
                Organization.is_active.is_(True),
            )
            .distinct()
        )
    ).scalars().all()
    return list(rows)


def build_alert(facts: BriefingFacts, lines: list[str]) -> Alert:
    """Wrap the digest for the bus.

    Severity is ``warning``, not ``info``, and that is not inflation: a new chat
    starts at ``min_severity=warning``, so an ``info`` briefing would be filtered
    out of every default install and the one message meant to build the habit
    would be the one nobody ever received. The same reasoning already applies to
    ``send_owner_document``.
    """
    return Alert(
        kind=AlertKind.briefing,
        severity=AlertSeverity.warning,
        title=f"Ertalabki xulosa · {facts.day.strftime('%d.%m.%Y')}",
        body="\n".join(lines),
        # Keyed on the day, so the four ticks inside the delivery window and a
        # worker restart all resolve to the one fact: this day was reported.
        dedupe_key=f"briefing:{facts.day.isoformat()}",
        path="/dashboard",
    )


async def run(db: AsyncSession) -> int:
    """Evaluate this signal across every organization and notify. Returns alerts sent.

    Called on every scheduler tick like the other watchers, and returns 0 on
    almost all of them: the hour gate is checked here rather than by a cron
    trigger so the target hour stays a plain setting instead of something baked
    into the job registration. Inside the window it is the bus's dedupe, not
    this function, that keeps four ticks down to one message.
    """
    if not settings.telegram_configured:
        return 0

    now_local = datetime.now(report_tz())
    if not _in_window(now_local):
        return 0
    day = now_local.date() - timedelta(days=1)

    sent = 0
    for org_id in await _listening_org_ids(db):
        try:
            facts = await collect(db, org_id, day)
            lines = await compose_with_ai(facts) or render_plain(facts)
            sent += await notify_owner(db, org_id, build_alert(facts, lines))
        except Exception:  # noqa: BLE001 — one org's bad data must not end the sweep.
            logger.exception("briefing_org_failed", org_id=str(org_id))
            try:
                await db.rollback()
            except Exception:  # noqa: BLE001
                logger.exception("briefing_rollback_failed", org_id=str(org_id))
    return sent
