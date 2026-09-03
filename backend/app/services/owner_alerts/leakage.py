"""Leakage watcher — the money already walking out of the gate.

``app.services.analytics`` finds fuel waste, unauthorized stops and suspicious
fill-ups, but only when somebody opens the Leakage page. Owners of mid-size
fleets do not open dashboards; they open Telegram. This module runs the same
three signals on the scheduler tick and pushes what is *new*.

Two problems have to be solved before any of that is safe to send.

**Identity.** The analytics functions recompute over a rolling window, so the
same real event comes back on every tick for as long as it stays inside the
window. The dedupe key therefore names the underlying fact, never its position
in the result list and never the sentence describing it:

* a stop is ``truck + the calendar day it began + where it happened``, rounded
  to a ~90 m bucket. Rounding is what makes it survivable: as the window's
  trailing edge slides forward, a stop that straddles it gets truncated and its
  ``started_at`` moves by minutes. A key built from the exact timestamp would
  read that as a brand-new stop and announce a week-old event twice.
* a suspicious fill-up is its ``fuel_logs`` row. That is a real database
  identity — stable, and unlike ``truck + day`` it keeps two bad fills on the
  same day as two separate things to check.
* a fuel-efficiency flag has no event behind it at all: it is a *state*
  measured over the trailing week, so it is keyed by truck and by the day it
  was measured. A truck that stays over baseline is worth one line a day, not
  one line every fifteen minutes.

``DEDUPE_TTL_HOURS`` is deliberately longer than the window. Both stops and
fill-ups sit inside a 7-day window for 7 days; with the bus's 24-hour default
every one of them would be re-announced a week's worth of times.

**Volume.** A fleet having a bad week can produce dozens of findings at once,
and thirty messages in a row is how an owner learns to mute the bot. One run
sends at most ``MAX_ALERTS_PER_ORG`` individual alerts, ranked worst-first, and
follows them with a single line saying how many are still queued. Nothing is
dropped: the remainder is left *unrecorded*, so the next tick picks it up and a
backlog drains a capful at a time instead of arriving as a wall of text.
"""
from __future__ import annotations

import html
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import logger
from app.models.organizations import Organization
from app.models.owner_alerts import NotificationLog, TelegramAccount
from app.services.analytics import (
    effective_window_days,
    fuel_anomalies,
    fuel_fraud_events,
    scan_tracks,
    unauthorized_stops,
)
from app.services.owner_alerts.bus import Alert, AlertKind, AlertSeverity, notify_owner
from app.services.period_reports import report_tz

WINDOW_DAYS = 7

# Long enough that a finding which lives in the rolling window for its full
# seven days is still remembered as "already told them" on the last day of it.
DEDUPE_TTL_HOURS = 24 * 14

MAX_ALERTS_PER_ORG = 5

# 3 decimal places ≈ 110 m of latitude and ~84 m of longitude at Tashkent's
# latitude — comfortably larger than GPS jitter at a truck stop, comfortably
# smaller than the distance between two different places to stop.
LOCATION_BUCKET_DP = 3

PANEL_PATH = "/leakage"

_CATEGORY_LABEL_UZ = {
    "fraud": "Shubhali yoqilg'i quyish",
    "fuel": "Ortiqcha yoqilg'i sarfi",
    "stop": "Ruxsatsiz to'xtash",
}

# Worst-first when the cap has to choose. A flagged fill-up is a receipt the
# owner can physically go and check; an efficiency flag is a statistical hint;
# a long stop is the softest of the three.
_CATEGORY_PRIORITY = {"fraud": 0, "fuel": 1, "stop": 2}

_REASON_LABEL_UZ = {
    "oversized_fill": "bak hajmidan ortiq quyilgan",
    "price_outlier": "narx odatdagidan yuqori",
    "excess_consumption": "masofaga nisbatan sarf haqiqatga to'g'ri kelmaydi",
}


@dataclass(frozen=True)
class _Finding:
    """One leakage fact, ready to be sent or counted into the roll-up."""

    category: str
    dedupe_key: str
    title: str
    body: str
    magnitude: float  # money or minutes — ranks findings within a category


# ── Formatting helpers ───────────────────────────────────────────────────


def _money(value: float) -> str:
    """Grouped by thousands with spaces, and with no currency symbol.

    Fuel costs are stored in whatever currency the company records them in
    (so'm for almost everyone, dollars for some cross-border operators) and
    nothing on ``FuelLog`` says which. Printing a bare number lets the owner
    read it in their own currency; printing "so'm" would be a guess.
    """
    return f"{value:,.0f}".replace(",", " ")


def _today_key() -> str:
    """The Tashkent calendar day, which is the one the owner is living in."""
    return datetime.now(report_tz()).date().isoformat()


def _local(moment: datetime) -> datetime:
    """Render times in Tashkent, the only clock the reader has.

    Naive datetimes are treated as UTC rather than handed to ``astimezone``,
    which would silently interpret them in the *server's* timezone and shift
    every stop by however many hours the host happens to be offset.
    """
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(report_tz())


def _duration_uz(minutes: float) -> str:
    hours, mins = divmod(int(round(minutes)), 60)
    return f"{hours} soat {mins} daqiqa" if hours else f"{mins} daqiqa"


def _maps_link(lat: float, lng: float) -> str:
    return f'<a href="https://maps.google.com/?q={lat},{lng}">xaritada ko\'rish</a>'


def _title(category: str, plate: str | None) -> str:
    return f"{_CATEGORY_LABEL_UZ[category]} — {plate or '—'}"


# ── Findings (pure: analytics dict in, alert material out) ───────────────


def _fuel_findings(report: dict, today: str) -> list[_Finding]:
    """Trucks burning materially more than the fleet's own median."""
    days = report.get("window_days", WINDOW_DAYS)
    findings = []
    for truck in report.get("trucks", []):
        if not truck.get("flagged"):
            continue
        waste = float(truck.get("estimated_waste_cost") or 0)
        body = "\n".join(
            [
                f"<b>{float(truck['l_per_100km']):.1f} L/100km</b>"
                f" — avtopark me'yori {float(truck['baseline_l_per_100km']):.1f} L/100km",
                f"{days} kunda: {_money(float(truck['liters']))} L"
                f" / {_money(float(truck['distance_km']))} km",
                f"Taxminiy ortiqcha xarajat: <b>{_money(waste)}</b>",
            ]
        )
        findings.append(
            _Finding(
                category="fuel",
                dedupe_key=f"leakage:fuel:{truck['truck_id']}:{today}",
                title=_title("fuel", truck.get("plate_number")),
                body=body,
                magnitude=waste,
            )
        )
    return findings


def _stop_findings(report: dict) -> list[_Finding]:
    """Long stops outside every depot and customer geofence."""
    findings = []
    for stop in report.get("stops", []):
        started = _local(stop["started_at"])
        lat = round(float(stop["latitude"]), LOCATION_BUCKET_DP)
        lng = round(float(stop["longitude"]), LOCATION_BUCKET_DP)
        minutes = float(stop["duration_minutes"])
        body = "\n".join(
            [
                f"Davomiyligi: <b>{_duration_uz(minutes)}</b>",
                f"Boshlangan: {started.strftime('%d.%m %H:%M')}",
                _maps_link(stop["latitude"], stop["longitude"]),
            ]
        )
        findings.append(
            _Finding(
                category="stop",
                dedupe_key=(
                    f"leakage:stop:{stop['truck_id']}:{started.date().isoformat()}:{lat}:{lng}"
                ),
                title=_title("stop", stop.get("plate_number")),
                body=body,
                magnitude=minutes,
            )
        )
    return findings


def _fraud_findings(report: dict) -> list[_Finding]:
    """Individual fill-ups that do not add up."""
    findings = []
    for event in report.get("events", []):
        reasons = ", ".join(
            _REASON_LABEL_UZ.get(reason, reason) for reason in event.get("reasons", [])
        )
        cost = float(event.get("total_cost") or 0)
        lines = [
            f"Sabab: <b>{html.escape(reasons)}</b>",
            f"{float(event['liters']):.0f} L × {_money(float(event['cost_per_liter']))}"
            f" = <b>{_money(cost)}</b>",
            f"Sana: {_local(event['filled_at']).strftime('%d.%m %H:%M')}",
        ]
        if event.get("fuel_station"):
            lines.append(f"Zapravka: {html.escape(event['fuel_station'])}")
        findings.append(
            _Finding(
                category="fraud",
                dedupe_key=f"leakage:fraud:{event['fuel_log_id']}",
                title=_title("fraud", event.get("plate_number")),
                body="\n".join(lines),
                magnitude=cost,
            )
        )
    return findings


def rank_findings(findings: list[_Finding]) -> list[_Finding]:
    """Worst first, so the five that fit under the cap are the five that matter.

    The dedupe key breaks ties: two stops of identical length must not swap
    places between ticks, or the cap would send a different pair each time and
    the backlog would never drain.
    """
    return sorted(
        findings,
        key=lambda f: (_CATEGORY_PRIORITY[f.category], -f.magnitude, f.dedupe_key),
    )


def _summary_alert(remainder: list[_Finding], today: str) -> Alert:
    """One line standing in for everything the cap held back.

    Counted by category rather than listed, and deduped by day: the owner needs
    to know a backlog exists once, not on every tick while it drains.
    """
    counts: dict[str, int] = {}
    for finding in remainder:
        counts[finding.category] = counts.get(finding.category, 0) + 1
    lines = [
        f"• {_CATEGORY_LABEL_UZ[category]} — {count} ta"
        for category, count in sorted(counts.items(), key=lambda kv: _CATEGORY_PRIORITY[kv[0]])
    ]
    lines.append("Qolganlari keyingi tekshiruvlarda yuboriladi.")
    return Alert(
        kind=AlertKind.leakage,
        severity=AlertSeverity.warning,
        title=f"Yana {len(remainder)} ta yo'qotish hodisasi aniqlandi",
        body="\n".join(lines),
        dedupe_key=f"leakage:summary:{today}",
        dedupe_ttl_hours=24,
        path=PANEL_PATH,
    )


# ── Persistence-facing helpers ───────────────────────────────────────────


async def _orgs_with_owner_chats(db: AsyncSession) -> list[uuid.UUID]:
    """Only organizations that can actually be told anything.

    The GPS scan behind these signals streams every position row in the window,
    so running it for a company that has never linked a chat is the most
    expensive way in this codebase to produce nothing.
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
            .order_by(TelegramAccount.org_id)
        )
    ).scalars().all()
    return list(rows)


async def _unreported(db: AsyncSession, org_id: uuid.UUID, keys: list[str]) -> set[str]:
    """Which of ``keys`` this org has not been told about inside the TTL.

    The bus checks this again per alert and remains the authority — this pass
    exists because the cap has to rank *new* findings. Capping the raw list
    instead would spend the whole budget re-suppressing facts already sent and
    report the genuinely new ones as "not listed".
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


async def collect_findings(db: AsyncSession, org_id: uuid.UUID) -> list[_Finding]:
    """Every leakage fact currently visible in one org's window."""
    gps_days = effective_window_days(WINDOW_DAYS)
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=gps_days)

    # One scan feeding both GPS-derived reports, exactly as the Leakage page
    # does — they cost a full pass over the position history each otherwise.
    tracks = await scan_tracks(db, start, end, org_id)
    fuel = await fuel_anomalies(db, gps_days, org_id, tracks=tracks)
    stops = await unauthorized_stops(db, gps_days, org_id, tracks=tracks)
    # Fill-ups are read from fuel logs alone, which are never purged, so this
    # one keeps the full requested window even where GPS retention is shorter.
    fraud = await fuel_fraud_events(db, WINDOW_DAYS, org_id)

    return _fuel_findings(fuel, _today_key()) + _stop_findings(stops) + _fraud_findings(fraud)


async def _run_for_org(db: AsyncSession, org_id: uuid.UUID) -> int:
    findings = await collect_findings(db, org_id)
    if not findings:
        return 0

    fresh_keys = await _unreported(db, org_id, [f.dedupe_key for f in findings])
    ranked = rank_findings([f for f in findings if f.dedupe_key in fresh_keys])
    if not ranked:
        return 0

    sent = 0
    for finding in ranked[:MAX_ALERTS_PER_ORG]:
        sent += await notify_owner(
            db,
            org_id,
            Alert(
                kind=AlertKind.leakage,
                # Never critical: every one of these is money already lost, and
                # nothing here is more actionable at 03:00 than at 08:00. Waking
                # an owner for it is how the whole bot gets muted.
                severity=AlertSeverity.warning,
                title=finding.title,
                body=finding.body,
                dedupe_key=finding.dedupe_key,
                dedupe_ttl_hours=DEDUPE_TTL_HOURS,
                path=PANEL_PATH,
            ),
        )

    remainder = ranked[MAX_ALERTS_PER_ORG:]
    if remainder:
        sent += await notify_owner(db, org_id, _summary_alert(remainder, _today_key()))

    logger.info(
        "leakage_watch_org_done",
        org_id=str(org_id),
        findings=len(findings),
        new=len(ranked),
        held_back=len(remainder),
        sent=sent,
    )
    return sent


async def run(db: AsyncSession) -> int:
    """Evaluate leakage across every organization and notify. Returns alerts sent.

    Never raises: one org whose scan blows up must not cost every other org its
    tick, and the scheduler must not lose the job to a single bad row.
    """
    if not settings.telegram_configured:
        return 0

    sent = 0
    for org_id in await _orgs_with_owner_chats(db):
        try:
            sent += await _run_for_org(db, org_id)
        except Exception:  # noqa: BLE001 — next org still deserves its alerts.
            logger.exception("leakage_watch_org_failed", org_id=str(org_id))
            try:
                await db.rollback()  # leave the session usable for the next org
            except Exception:  # noqa: BLE001
                logger.exception("leakage_watch_rollback_failed", org_id=str(org_id))
    return sent
