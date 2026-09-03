"""The monthly close: two workbooks, once, on the 1st.

Everything worth testing here is about *when*, not *what* — the workbooks
themselves are covered by tests/test_period_reports.py and
tests/test_country_expenses.py. This job runs on a fifteen-minute tick, so the
1st of the month offers it ninety-six chances to send the same file, and a
close that fires on the wrong day reports a month that has not finished. Both
failures look like working software right up until an owner mutes the bot.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models.enums import TripReportCountry, TripReportExpenseCategory, TripStatus
from app.models.organizations import Organization
from app.models.owner_alerts import AlertSeverity, NotificationLog, TelegramAccount
from app.models.trip_reports import TripCountryExpenseLine, TripExpenseReport
from app.models.trips import Trip
from app.services.owner_alerts import bus, reports
from app.services.owner_alerts.reports import run
from app.services.period_reports import PeriodReport, resolve_period
from app.services.telegram import SendResult

# The tick this job is meant to fire on, and the month it must report.
FIRST_OF_SEPTEMBER = date(2026, 9, 1)
MID_AUGUST = datetime(2026, 8, 15, 9, 0, tzinfo=timezone.utc)
MID_SEPTEMBER = datetime(2026, 9, 1, 6, 0, tzinfo=timezone.utc)


@pytest.fixture
def captured_docs(monkeypatch) -> list[dict]:
    """Replace the file transport and switch the bot's feature gate on."""
    monkeypatch.setattr(settings, "telegram_bot_token", "TEST:token", raising=False)
    docs: list[dict] = []

    async def _fake_send_document(chat_id, filename, content, caption):
        docs.append(
            {"chat_id": chat_id, "filename": filename, "content": content, "caption": caption}
        )
        return SendResult(ok=True, status_code=200)

    monkeypatch.setattr(bus, "_send_document", _fake_send_document)
    return docs


async def _org_with_chat(db, *, name="Zafar Logistics", chat_id="900001", rates=True) -> uuid.UUID:
    org = Organization(
        name=name,
        usd_to_kzt=470 if rates else None,
        usd_to_rub=90 if rates else None,
        usd_to_uzs=12500 if rates else None,
    )
    db.add(org)
    await db.flush()
    db.add(
        TelegramAccount(
            org_id=org.id,
            token=uuid.uuid4().hex,
            chat_id=chat_id,
            min_severity=AlertSeverity.info,
            # No quiet window: the suite runs at whatever hour CI happens to
            # start, and the default 22→07 would make these tests pass or fail
            # depending on the clock.
            quiet_from_hour=None,
            quiet_to_hour=None,
        )
    )
    await db.commit()
    return org.id


async def _delivered_trip(db, org_id, *, delivered: datetime, rate: int = 50_000_000) -> Trip:
    trip = Trip(
        org_id=org_id,
        reference=f"TR-{uuid.uuid4().hex[:8]}",
        status=TripStatus.delivered,
        delivered_at=delivered,
        rate=rate,
    )
    db.add(trip)
    await db.commit()
    return trip


async def _filled_expense_form(db, org_id, trip: Trip, *, amount: int = 450_000) -> None:
    """A driver's yo'l varaqasi with one Kazakh cell on it."""
    report = TripExpenseReport(org_id=org_id, trip_id=trip.id, report_date=date(2026, 8, 20))
    db.add(report)
    await db.flush()
    db.add(
        TripCountryExpenseLine(
            report_id=report.id,
            country=TripReportCountry.kz,
            category=TripReportExpenseCategory.platon,
            amount=amount,
        )
    )
    await db.commit()


def _captions(docs: list[dict]) -> str:
    return "\n".join(doc["caption"] for doc in docs)


# ── When it fires ────────────────────────────────────────────────────────


async def test_no_workbook_goes_out_on_any_day_but_the_first(db, captured_docs):
    """The gate is a day check, so every other tick of the month must be a no-op."""
    org_id = await _org_with_chat(db)
    await _delivered_trip(db, org_id, delivered=MID_AUGUST)

    assert await run(db, today=date(2026, 9, 15)) == 0
    assert await run(db, today=date(2026, 9, 30)) == 0
    assert captured_docs == []


async def test_the_close_is_sent_once_however_many_ticks_land_on_the_first(db, captured_docs):
    """The load-bearing case.

    The scheduler runs this job every fifteen minutes, which is ninety-six
    ticks on the 1st. Without the dedupe key naming the period, the day check
    would send the same workbook ninety-six times before lunch.
    """
    org_id = await _org_with_chat(db)
    await _delivered_trip(db, org_id, delivered=MID_AUGUST)

    assert await run(db, today=FIRST_OF_SEPTEMBER) == 1
    assert await run(db, today=FIRST_OF_SEPTEMBER) == 0
    assert await run(db, today=FIRST_OF_SEPTEMBER) == 0
    assert len(captured_docs) == 1


async def test_each_month_is_its_own_fact_so_the_next_close_still_arrives(db, captured_docs):
    """Dedupe suppresses a repeat, not a successor. A key without the period in
    it would silence every close after the first one, forever."""
    org_id = await _org_with_chat(db)
    await _delivered_trip(db, org_id, delivered=MID_AUGUST)
    await _delivered_trip(db, org_id, delivered=MID_SEPTEMBER)

    assert await run(db, today=FIRST_OF_SEPTEMBER) == 1
    assert await run(db, today=date(2026, 10, 1)) == 1

    assert [doc["filename"] for doc in captured_docs] == [
        "hisobot-oylik-2026-08-01.xlsx",
        "hisobot-oylik-2026-09-01.xlsx",
    ]


def test_the_dedupe_key_names_the_period_in_machine_form():
    """Keyed on ``2026-08`` rather than on "2026 avgust": the label is display
    text, and rewording a month name must not re-close a year of months into
    everybody's chat."""
    august = resolve_period("month", 1, today=FIRST_OF_SEPTEMBER)
    september = resolve_period("month", 1, today=date(2026, 10, 1))

    assert reports._dedupe_key("month", august) == "report:month:2026-08"
    assert reports._dedupe_key("month", september) == "report:month:2026-09"
    # The two documents of one close are two facts, not one.
    assert reports._dedupe_key("country", august) != reports._dedupe_key("month", august)


# ── What it reports ──────────────────────────────────────────────────────


async def test_the_workbook_covers_last_month_not_the_one_that_just_started(db, captured_docs):
    """Sent on the 1st, so "this month" is a few hours old and empty."""
    org_id = await _org_with_chat(db)
    await _delivered_trip(db, org_id, delivered=MID_AUGUST)
    await _delivered_trip(db, org_id, delivered=MID_SEPTEMBER)

    await run(db, today=FIRST_OF_SEPTEMBER)

    assert captured_docs[0]["filename"] == "hisobot-oylik-2026-08-01.xlsx"
    assert "2026 avgust" in captured_docs[0]["caption"]
    assert "Yetkazilgan reyslar: 1" in captured_docs[0]["caption"]


async def test_the_month_boundary_is_a_tashkent_one_not_a_utc_one(db, captured_docs):
    """A trip delivered at 02:00 Tashkent on 1 August is August's revenue.

    In UTC it is still 31 July, so a close written against ``date.today()`` in
    UTC would file it into the previous month's report — and drop 1 September's
    early hours into August's.
    """
    org_id = await _org_with_chat(db)
    await _delivered_trip(db, org_id, delivered=datetime(2026, 7, 31, 21, 0, tzinfo=timezone.utc))
    await _delivered_trip(db, org_id, delivered=datetime(2026, 8, 31, 20, 0, tzinfo=timezone.utc))

    await run(db, today=FIRST_OF_SEPTEMBER)

    assert "Yetkazilgan reyslar: 1" in captured_docs[0]["caption"]


async def test_the_caption_carries_the_numbers_someone_would_read_on_a_phone(db, captured_docs):
    """The file is the document; the caption is what gets read in the chat."""
    org_id = await _org_with_chat(db)
    await _delivered_trip(db, org_id, delivered=MID_AUGUST, rate=50_000_000)

    await run(db, today=FIRST_OF_SEPTEMBER)

    caption = captured_docs[0]["caption"]
    assert "50 000 000 so'm" in caption  # grouped the way the amount is written here
    assert "Foyda" in caption


def test_the_caption_withholds_a_consumption_figure_the_report_calls_unreliable():
    """``consumption_reliable`` exists because litres bought is not litres
    burned. A caption that prints the ratio anyway is the version people quote
    at a driver, so it must honour the report's own answer."""
    period = resolve_period("month", 1, today=FIRST_OF_SEPTEMBER)
    report = PeriodReport(
        period=period,
        organization="Zafar Logistics",
        generated_at=datetime.now(timezone.utc),
        trips_delivered=4,
        revenue=100_000_000,
        fuel_liters=1200,
        distance_km=4000,
        trucks_moved=3,
        fills=1,  # one fill covering three trucks: the ratio means nothing
    )
    assert "l/100km" not in reports._period_caption(report)

    report.fills = 5
    assert "l/100km" in reports._period_caption(report)


# ── Who gets one ─────────────────────────────────────────────────────────


async def test_an_organization_with_no_trips_gets_no_workbook(db, captured_docs):
    """A file full of zeros is how an owner learns this bot's attachments are
    not worth opening. Nothing is recorded either, so the org is re-evaluated
    normally next month."""
    await _org_with_chat(db)

    assert await run(db, today=FIRST_OF_SEPTEMBER) == 0
    assert captured_docs == []
    assert (await db.execute(select(NotificationLog))).scalars().all() == []


async def test_an_organization_with_no_linked_chat_is_never_computed(db, captured_docs, monkeypatch):
    """Building a period report walks a month of GPS history for every truck.
    Doing that for an org whose file has nowhere to go is minutes of work the
    bus discards on its first line."""
    org = Organization(name="No Chat Co")
    db.add(org)
    await db.commit()
    await _delivered_trip(db, org.id, delivered=MID_AUGUST)

    built: list[uuid.UUID] = []
    real_build = reports.build_period_report

    async def _counting_build(session, org_id, period):
        built.append(org_id)
        return await real_build(session, org_id, period)

    monkeypatch.setattr(reports, "build_period_report", _counting_build)

    assert await run(db, today=FIRST_OF_SEPTEMBER) == 0
    assert built == []


async def test_a_close_never_reaches_another_organization(db, captured_docs):
    """One tick serves every tenant, so a missing org filter here leaks one
    customer's revenue into another's chat."""
    org_a = await _org_with_chat(db, name="A Co", chat_id="900001")
    await _org_with_chat(db, name="B Co", chat_id="900002")
    await _delivered_trip(db, org_a, delivered=MID_AUGUST)

    await run(db, today=FIRST_OF_SEPTEMBER)

    assert [doc["chat_id"] for doc in captured_docs] == ["900001"]


async def test_a_suspended_organization_is_not_closed(db, captured_docs):
    """An offboarded customer keeps their data and stops hearing from us."""
    org_id = await _org_with_chat(db)
    await _delivered_trip(db, org_id, delivered=MID_AUGUST)
    org = await db.get(Organization, org_id)
    org.is_active = False
    await db.commit()

    assert await run(db, today=FIRST_OF_SEPTEMBER) == 0
    assert captured_docs == []


# ── The country-expense workbook ─────────────────────────────────────────


async def test_the_country_breakdown_travels_with_the_close(db, captured_docs):
    """The two files an accountant asks for on the 1st, in one delivery."""
    org_id = await _org_with_chat(db)
    trip = await _delivered_trip(db, org_id, delivered=MID_AUGUST)
    await _filled_expense_form(db, org_id, trip)

    assert await run(db, today=FIRST_OF_SEPTEMBER) == 2

    names = [doc["filename"] for doc in captured_docs]
    assert names[0] == "hisobot-oylik-2026-08-01.xlsx"
    assert names[1] == "reys-xarajatlari-20260801-20260831.xlsx"
    assert "450 000 KZT" in captured_docs[1]["caption"]
    assert "$957" in captured_docs[1]["caption"]  # 450 000 KZT at the org's own rate
    # Real workbooks, not the empty bytes a swallowed render would leave behind.
    assert all(doc["content"][:2] == b"PK" for doc in captured_docs)


async def test_a_month_whose_drivers_filed_no_forms_sends_only_the_period_report(
    db, captured_docs
):
    """The country breakdown is built from the yo'l varaqasi and from nothing
    else, so with no form filled it has no rows — and a workbook of three empty
    country sheets is not a document."""
    org_id = await _org_with_chat(db)
    await _delivered_trip(db, org_id, delivered=MID_AUGUST)

    assert await run(db, today=FIRST_OF_SEPTEMBER) == 1
    assert [doc["filename"] for doc in captured_docs] == ["hisobot-oylik-2026-08-01.xlsx"]


async def test_the_caption_says_when_the_dollar_column_is_incomplete(db, captured_docs):
    """Without a rate the USD total is short by whatever was spent in that
    country. Printing the smaller number silently is the failure mode; the only
    fix is a rate somebody has to type into Settings."""
    org_id = await _org_with_chat(db, rates=False)
    trip = await _delivered_trip(db, org_id, delivered=MID_AUGUST)
    await _filled_expense_form(db, org_id, trip)

    await run(db, today=FIRST_OF_SEPTEMBER)

    country_caption = captured_docs[1]["caption"]
    assert "KZ uchun kurs kiritilmagan" in country_caption
    assert "Jami: $" not in country_caption


# ── Surviving a bad tick ─────────────────────────────────────────────────


async def test_one_organizations_broken_report_does_not_cost_the_others_theirs(
    db, captured_docs, monkeypatch
):
    """A single tenant with data that crashes a report would otherwise take the
    whole platform's month-end with it — and the dedupe row for the orgs that
    did get served is what stops the retry from double-sending."""
    org_a = await _org_with_chat(db, name="A Co", chat_id="900001")
    org_b = await _org_with_chat(db, name="B Co", chat_id="900002")
    await _delivered_trip(db, org_a, delivered=MID_AUGUST)
    await _delivered_trip(db, org_b, delivered=MID_AUGUST)

    real_build = reports.build_period_report
    calls: list[uuid.UUID] = []

    async def _first_org_explodes(session, org_id, period):
        calls.append(org_id)
        if len(calls) == 1:
            raise RuntimeError("corrupt fuel row")
        return await real_build(session, org_id, period)

    monkeypatch.setattr(reports, "build_period_report", _first_org_explodes)

    assert await run(db, today=FIRST_OF_SEPTEMBER) == 1
    assert len(captured_docs) == 1


async def test_nothing_is_sent_while_the_bot_is_unconfigured(db, monkeypatch):
    """A deployment with no bot token must not spend minutes building workbooks
    nobody can receive — and must not record them as delivered either."""
    monkeypatch.setattr(settings, "telegram_bot_token", "", raising=False)
    org_id = await _org_with_chat(db)
    await _delivered_trip(db, org_id, delivered=MID_AUGUST)

    assert await run(db, today=FIRST_OF_SEPTEMBER) == 0
    assert (await db.execute(select(NotificationLog))).scalars().all() == []


async def test_an_org_with_two_linked_chats_is_computed_once_and_served_twice(
    db, captured_docs, monkeypatch
):
    """The director and the accountant both get the file, and the fleet's month
    of GPS history is only walked for it once."""
    org_id = await _org_with_chat(db, chat_id="900001")
    db.add(
        TelegramAccount(
            org_id=org_id,
            token=uuid.uuid4().hex,
            chat_id="900002",
            min_severity=AlertSeverity.info,
            quiet_from_hour=None,
            quiet_to_hour=None,
        )
    )
    await db.commit()
    await _delivered_trip(db, org_id, delivered=MID_AUGUST)

    builds: list[uuid.UUID] = []
    real_build = reports.build_period_report

    async def _counting_build(session, org, period):
        builds.append(org)
        return await real_build(session, org, period)

    monkeypatch.setattr(reports, "build_period_report", _counting_build)

    assert await run(db, today=FIRST_OF_SEPTEMBER) == 2
    assert len(builds) == 1
    assert sorted(doc["chat_id"] for doc in captured_docs) == ["900001", "900002"]
