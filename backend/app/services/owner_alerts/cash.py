"""Kassa nazoratchisi — the trip whose cash does not add up.

A driver leaves the yard with dollars, roubles, tenge and so'm in an envelope,
changes some of it at a border booth, and spends the rest on diesel, Platon,
fines and food. When he gets back he fills a "yo'l varaqasi" and
:func:`app.services.trip_reports.compute_report_totals` nets each currency:
issued + exchanged-in − spent. A balance far from zero is the one number on
that form nobody can explain away — either cash left the envelope without a
receipt, or money was spent that the company never issued.

Three decisions shape this watcher:

**The threshold is a dollar, not a currency.** 50 000 UZS is four dollars and
200 000 KZT is four hundred; a single per-currency number that catches the
second without drowning the owner in the first does not exist. So where the
organization has configured a rate the balance is converted and judged against
one USD threshold, and only an organization that has configured nothing falls
back to a per-currency figure.

**The rate comes from the organization, never from the trip.**
:func:`app.services.country_expenses.resolve_rates` prefers the rate a trip
actually got at the booth, and for *reporting* that is the truer number. Here
it would be circular: the form under audit would supply the yardstick that
decides whether the form is wrong, and a mistyped — or invented — exchange row
is exactly the thing this alert exists to surface.

**One report version, one alert.** The scheduler re-evaluates every fifteen
minutes and a mismatch stays a mismatch, so the dedupe key carries the
report's ``updated_at``: an untouched report is announced once and never
again, while a driver who corrects his figures and resubmits is judged afresh
against the numbers he just changed.
"""
from __future__ import annotations

import html
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Mapping

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.logging import logger
from app.models.enums import TripReportStatus
from app.models.organizations import Organization
from app.models.trip_reports import TripExpenseReport
from app.models.trips import Trip
from app.services.owner_alerts.bus import Alert, AlertKind, AlertSeverity, notify_owner
from app.services.trip_reports import compute_report_totals

__all__ = ["Gap", "build_alert", "find_gaps", "org_rates", "run"]

# What counts as money missing rather than arithmetic. Anchored on the dollar:
# below one tank of diesel (a Kazakh fill-up runs $300–400), far above the
# rounding a driver does writing 5 000 tenge for a lunch that cost 4 800. Any
# lower and the alert fires on every honest report; any higher and a whole
# border bribe fits under it unnoticed.
USD_THRESHOLD = 50.0

# The same fifty dollars in each currency, at the rates that held when this was
# written (≈12 800 UZS, ≈460 KZT, ≈90 RUB to the dollar) and rounded to a
# number an owner recognises. Used ONLY when the organization has configured no
# rate of its own — which also means they drift with the exchange rate and are
# a reason to configure one, not a substitute for it.
NATIVE_THRESHOLDS: dict[str, float] = {
    "usd": USD_THRESHOLD,
    "rub": 5_000.0,
    "kzt": 25_000.0,
    "uzs": 600_000.0,
}

CURRENCY_LABEL: dict[str, str] = {"usd": "USD", "rub": "RUB", "kzt": "KZT", "uzs": "UZS"}

# Dollars first, then the currencies in the order the money is spent driving
# north — home, Kazakhstan, Russia. Iterating this rather than the balances
# dict keeps the message stable between runs.
CURRENCY_ORDER: tuple[str, ...] = ("usd", "uzs", "kzt", "rub")

# How far back a submission is still news. Two purposes: an owner switching
# this on does not get a year of settled trips fired at them in one tick, and a
# mismatch nobody chased for a week is not going to be chased by a chat
# message. Kept well inside the 30-day default of
# :func:`prune_notification_log` so a pruned dedupe row can never resurrect an
# alert the owner already read.
LOOKBACK_DAYS = 7

# Longer than the lookback window by a wide margin: within it every report is
# judged by identity (id + updated_at), and a report that ages out of the
# window is never queried again, so the TTL never has to expire for the system
# to stay correct.
DEDUPE_TTL_HOURS = 24 * 21


@dataclass(frozen=True)
class Gap:
    """One currency whose balance is too far from zero to be rounding."""

    currency: str
    # Signed, in the driver's own currency: positive means cash was issued and
    # never accounted for, negative means more was spent than was ever handed
    # out. Both are mismatches; they are different conversations.
    amount: float
    # ``abs(amount)`` in dollars, or None when no rate was configured for this
    # currency and the native fallback decided the case.
    usd: float | None

    @property
    def unaccounted(self) -> bool:
        return self.amount > 0


def org_rates(org: Organization | None) -> dict[str, float | None]:
    """How many units of each currency one dollar buys, per this organization.

    The dollar is its own yardstick and is always present; the other three are
    ``None`` until an admin fills them in, which is what pushes the comparison
    onto :data:`NATIVE_THRESHOLDS`.
    """

    def _positive(value) -> float | None:
        rate = float(value) if value is not None else 0.0
        return rate if rate > 0 else None

    return {
        "usd": 1.0,
        "uzs": _positive(org.usd_to_uzs if org else None),
        "kzt": _positive(org.usd_to_kzt if org else None),
        "rub": _positive(org.usd_to_rub if org else None),
    }


def find_gaps(
    balances: Mapping[str, float], rates: Mapping[str, float | None]
) -> list[Gap]:
    """Every currency in ``balances`` whose imbalance is worth a message."""
    gaps: list[Gap] = []
    for currency in CURRENCY_ORDER:
        amount = round(float(balances.get(currency) or 0.0), 2)
        if amount == 0.0:
            continue
        rate = rates.get(currency)
        if rate:
            usd = round(abs(amount) / rate, 2)
            over = usd >= USD_THRESHOLD
        else:
            usd = None
            over = abs(amount) >= NATIVE_THRESHOLDS[currency]
        if over:
            gaps.append(Gap(currency=currency, amount=amount, usd=usd))
    return gaps


def _fmt_amount(currency: str, amount: float) -> str:
    """Group thousands with spaces, the way a so'm figure is written by hand.

    Tiyin do not exist in practice, so only the dollar keeps its decimals — two
    decimal places on 1 250 000 so'm is noise in a message read on a phone.
    """
    digits = 2 if currency == "usd" else 0
    return f"{abs(amount):,.{digits}f}".replace(",", " ")


def _esc(value: str) -> str:
    # quote=False: these land in text content, and escaping apostrophes turns
    # every Uzbek name and plate note into &#x27; soup.
    return html.escape(value, quote=False)


def _dedupe_key(report: TripExpenseReport) -> str:
    """Identity of the fact: *this version* of *this report*.

    Folding ``updated_at`` in is the whole trick. Without it a corrected
    resubmission is silently swallowed as "already reported"; with it the
    corrected numbers are evaluated on their own merits and, if they now
    reconcile, nothing is sent at all.
    """
    stamp = report.updated_at or report.created_at or datetime.now(timezone.utc)
    if stamp.tzinfo is None:  # a naive column value would raise on .timestamp()
        stamp = stamp.replace(tzinfo=timezone.utc)
    return f"cash:{report.id}:{int(stamp.timestamp())}"


def build_alert(report: TripExpenseReport, trip: Trip, gaps: list[Gap]) -> Alert:
    """Compose the message. Pure, so the wording is testable without a database."""
    lines: list[str] = []
    if report.driver_name:
        lines.append(f"👤 {_esc(report.driver_name)}")
    if report.plate_number:
        lines.append(f"🚛 {_esc(report.plate_number)}")
    if lines:
        lines.append("")  # who it was, then a beat, then the numbers

    for gap in gaps:
        verdict = "hisobsiz qoldi" if gap.unaccounted else "ortiqcha sarflangan"
        amount = f"{_fmt_amount(gap.currency, gap.amount)} {CURRENCY_LABEL[gap.currency]}"
        usd_note = ""
        # Suppress the conversion on the dollar row itself — "120.00 USD (≈ $120)"
        # tells the reader nothing they did not just read.
        if gap.usd is not None and gap.currency != "usd":
            usd_note = f" (≈ ${gap.usd:,.0f})".replace(",", " ")
        lines.append(f"• <b>{_esc(amount)}</b> {verdict}{usd_note}")

    converted = [gap.usd for gap in gaps if gap.usd is not None]
    if len(converted) > 1:
        total = f"{sum(converted):,.0f}".replace(",", " ")
        lines.append(f"Jami farq: ≈ <b>${total}</b>")

    return Alert(
        kind=AlertKind.cash_mismatch,
        # Deliberately not critical, however large the sum. Critical is the one
        # level that overrides quiet hours, and a report submitted at 02:00
        # describes money that was already spent days ago in another country —
        # waking the owner buys nothing and costs the bot its welcome.
        severity=AlertSeverity.warning,
        title=f"Kassa hisobi to'g'ri kelmadi — {trip.reference}",
        body="\n".join(lines),
        dedupe_key=_dedupe_key(report),
        dedupe_ttl_hours=DEDUPE_TTL_HOURS,
        path=f"/trips/{trip.id}",
    )


async def _recent_submissions(
    db: AsyncSession,
) -> list[tuple[TripExpenseReport, Trip, Organization]]:
    """Submitted reports touched inside the lookback window, across every org.

    One of the few queries in the codebase that deliberately spans tenants —
    the watcher's job is the whole platform. The boundary is re-imposed on the
    way out: every alert is addressed to ``report.org_id``, and the
    organization joined here is joined on that same column, so one customer's
    exchange rate can never be used to judge another's report.

    Drafts are excluded on purpose. A half-filled form does not reconcile by
    definition, and alerting on one would train the owner that this alert means
    nothing.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)
    result = await db.execute(
        select(TripExpenseReport, Trip, Organization)
        .join(Trip, Trip.id == TripExpenseReport.trip_id)
        .join(Organization, Organization.id == TripExpenseReport.org_id)
        .where(
            TripExpenseReport.status == TripReportStatus.submitted,
            TripExpenseReport.updated_at >= cutoff,
        )
        .options(
            # compute_report_totals reads both collections; under the async ORM
            # a lazy load outside an await raises MissingGreenlet.
            selectinload(TripExpenseReport.fuel_rows),
            selectinload(TripExpenseReport.country_expenses),
        )
        .order_by(TripExpenseReport.updated_at)
    )
    return list(result.all())


async def run(db: AsyncSession) -> int:
    """Evaluate every recent submission across every organization and notify.

    Returns the number of chats messaged. Never raises: a scheduler tick that
    dies on one malformed report stops checking every other org's cash too.
    """
    try:
        rows = await _recent_submissions(db)
    except Exception:  # noqa: BLE001
        logger.exception("cash_watcher_query_failed")
        return 0

    sent = 0
    for report, trip, org in rows:
        try:
            totals = compute_report_totals(report, report.fuel_rows, report.country_expenses)
            gaps = find_gaps(totals.currency_balances, org_rates(org))
            if not gaps:
                continue
            sent += await notify_owner(db, report.org_id, build_alert(report, trip, gaps))
        except Exception:  # noqa: BLE001 — one bad report must not hide the rest.
            logger.exception("cash_watcher_report_failed", report_id=str(report.id))
    return sent
