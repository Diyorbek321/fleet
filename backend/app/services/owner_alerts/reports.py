"""Month-end closing documents, pushed to the owner's chat on the 1st.

Both workbooks already exist and both are already right; what is missing is
that somebody has to remember to go and fetch them. A close happens once a
month, on a day nobody has any other reason to open the panel, and the two
files an accountant actually asks for — the period report and the
country-expense breakdown — sit behind a date picker that defaults to "last 30
days". So this job walks that path on the owner's behalf and delivers the
finished .xlsx to the chat they already read.

**Why the schedule is a check at the top of the function.** The scheduler ticks
every fifteen minutes, which makes the 1st of the month ninety-six chances to
send the same workbook. :mod:`app.services.daily_updates` has the same problem
and answers it the same way — look at the clock inside the job rather than
teaching APScheduler a cron expression — and this module copies it on purpose:
one place to read "when does this fire", instead of a schedule living half in a
settings value and half in a trigger. The day check on its own is not enough,
because it is equally true on all ninety-six ticks; what makes the close fire
exactly once is that the dedupe key names the *period*, so every tick after the
first asks the bus about a fact it has already recorded as reported.

Dates are Tashkent dates. For the first five hours of the 1st UTC it is still
the 31st here, and an owner who receives "2026 avgust" on the evening of the
31st of August has been handed the summary of a month that has not finished.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger
from app.models.organizations import Organization
from app.models.owner_alerts import TelegramAccount
from app.services import country_expense_xlsx, period_report_xlsx
from app.services.country_expenses import CountryExpenseReport, build_country_expense_report
from app.services.owner_alerts.bus import AlertKind, send_owner_document
from app.services.period_reports import (
    Period,
    PeriodReport,
    build_period_report,
    report_tz,
    resolve_period,
)

# Local day-of-month the books are closed on.
CLOSING_DAY = 1

# Longer than the single day the gate allows, shorter than the horizon
# ``prune_notification_log`` sweeps at. A day of ticks spans just under twenty-
# four hours, so the bus's default TTL clears it by minutes and nothing else;
# a week of margin costs nothing and takes the question off the table.
DEDUPE_TTL_HOURS = 24 * 7


# ── Entry point ──────────────────────────────────────────────────────────


async def run(db: AsyncSession, *, today: date | None = None) -> int:
    """Hand every organization last month's closing documents. Returns chats sent to.

    ``today`` is injectable so a test — and a manual catch-up run after an
    outage on the 1st — does not have to wait for the calendar. The scheduler
    always calls this with nothing.
    """
    today = today or datetime.now(report_tz()).date()
    if today.day != CLOSING_DAY:
        return 0

    period = resolve_period("month", 1, today=today)

    sent = 0
    for org_id in await _organizations_to_close(db):
        try:
            sent += await _close_organization(db, org_id, period)
        except Exception:  # noqa: BLE001 — one org's bad data must not cost the rest theirs.
            logger.exception("monthly_close_failed", org_id=str(org_id), period=period.label)
            await _recover(db)

    if sent:
        logger.info("monthly_close_sent", period=period.label, chats=sent)
    return sent


async def _recover(db: AsyncSession) -> None:
    """Leave the session usable for the organizations still queued behind this one."""
    try:
        await db.rollback()
    except Exception:  # noqa: BLE001
        logger.exception("monthly_close_rollback_failed")


async def _organizations_to_close(db: AsyncSession) -> list[uuid.UUID]:
    """Active organizations that have somewhere for a file to go.

    Filtered here rather than left to the bus's own gate because building a
    period report is the heaviest read in this codebase — it walks a month of
    GPS history for every truck in the fleet — and for an organization with no
    linked chat every second of it would be discarded by the first check inside
    ``send_owner_document``.
    """
    rows = await db.execute(
        select(Organization.id)
        .join(TelegramAccount, TelegramAccount.org_id == Organization.id)
        .where(
            Organization.is_active.is_(True),
            TelegramAccount.is_active.is_(True),
            TelegramAccount.chat_id.is_not(None),
        )
        .distinct()
    )
    return list(rows.scalars().all())


async def _close_organization(db: AsyncSession, org_id: uuid.UUID, period: Period) -> int:
    """Both workbooks for one organization, each judged on its own emptiness."""
    sent = 0

    report = await build_period_report(db, org_id, period)
    # A month with no delivered trip has nothing to close. Sending the workbook
    # anyway is worse than sending nothing: a file full of zeros is how an owner
    # learns that this bot's attachments are not worth opening.
    if report.trips_delivered:
        sent += await send_owner_document(
            db,
            org_id,
            filename=period_report_xlsx.filename_for(report),
            content=period_report_xlsx.build_workbook(report),
            caption=_period_caption(report),
            dedupe_key=_dedupe_key("month", period),
            dedupe_ttl_hours=DEDUPE_TTL_HOURS,
            kind=AlertKind.report_ready,
        )

    # Asked separately rather than skipped along with the period report: the
    # country breakdown files a trip by *departure* when it has not arrived yet,
    # so a month whose runs all delivered in the next one still holds real
    # spending — and, the other way round, a delivered month whose drivers filed
    # no forms holds none.
    countries = await build_country_expense_report(
        db, org_id, start=period.start, end=period.end
    )
    if countries.trips:
        sent += await send_owner_document(
            db,
            org_id,
            filename=country_expense_xlsx.filename_for(countries),
            content=country_expense_xlsx.build_workbook(countries),
            caption=_country_caption(countries, period),
            dedupe_key=_dedupe_key("country", period),
            dedupe_ttl_hours=DEDUPE_TTL_HOURS,
            kind=AlertKind.report_ready,
        )

    return sent


def _dedupe_key(document: str, period: Period) -> str:
    """Identity of "this document, for this month".

    The period is written machine-side (``2026-08``) rather than as
    ``period.label``: the label is Uzbek display text, and one edit to a month
    name would change every key ever minted and re-close a year of months into
    everybody's chat.
    """
    return f"report:{document}:{period.start:%Y-%m}"


# ── Captions ─────────────────────────────────────────────────────────────
#
# Sent with parse_mode HTML and deliberately built from nothing but numbers and
# the generated period label — every name in this data (organization, truck,
# driver, shipper) stays inside the workbook, so there is no user input here to
# escape and no way for a plate number containing "<" to break the message.


def _uzs(value: float) -> str:
    """``12 400 000`` — grouped with spaces, the way the amount is written here."""
    return f"{value:,.0f}".replace(",", " ")


def _period_caption(report: PeriodReport) -> str:
    lines = [
        f"📊 <b>{report.period.label}</b> — oylik hisobot",
        "",
        f"Yetkazilgan reyslar: {report.trips_delivered}",
        f"Daromad: {_uzs(report.revenue)} so'm",
        f"Xarajat: {_uzs(report.total_cost)} so'm",
        f"Foyda: <b>{_uzs(report.profit)} so'm</b> ({report.margin_pct}%)",
    ]
    # ``consumption_reliable`` is the report's own answer to whether litres per
    # 100 km may be stated as a fact at all, and a caption is the worst place to
    # overrule it — the caption is the line people quote at a driver.
    if report.consumption_reliable and report.l_per_100km is not None:
        lines.append(f"Yoqilg'i: {report.l_per_100km} l/100km")
    if report.distance_partial:
        lines.append("⚠️ Masofa qisman: GPS tarixi butun oyni qamrab olmaydi")
    return "\n".join(lines)


def _country_caption(report: CountryExpenseReport, period: Period) -> str:
    lines = [
        f"🌍 <b>{period.label}</b> — davlatlar bo'yicha xarajat",
        "",
        f"Reyslar: {len(report.trips)}",
    ]
    for block in report.countries:
        if block.is_empty:
            continue
        lines.append(f"{block.country.upper()}: {_uzs(block.total)} {block.currency}")
    if report.total_usd is not None:
        lines.append(f"Jami: <b>${_uzs(report.total_usd)}</b>")
    # Named, not hidden: the dollar column is short by whatever was spent in the
    # countries listed here, and the only thing that fixes it is a rate someone
    # has to type into Settings.
    if report.countries_missing_rate:
        codes = ", ".join(code.upper() for code in report.countries_missing_rate)
        lines.append(f"⚠️ {codes} uchun kurs kiritilmagan — dollar summasi to'liq emas")
    elif report.usd_partial:
        lines.append("⚠️ Ba'zi reyslarda kurs yo'q — dollar summasi to'liq emas")
    return "\n".join(lines)
