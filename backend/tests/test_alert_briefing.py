"""The morning digest — and, mostly, the gate that keeps a model out of the numbers.

Two things can go wrong here and only one of them is a bug in the ordinary sense.

The first is arithmetic: "kecha" has to mean the owner's yesterday, in Tashkent,
and one organization's litres must never appear in another's message. Those are
tested against a real database because that is where the timezone and the
tenancy live.

The second is worse and quieter. The model is handed real figures and asked to
phrase them; if it rounds one, sums two, or invents a litre count, the owner
reads a money report that disagrees with the panel and stops believing both.
Most of what follows pins that shut: every number the model writes must be one
we measured, or the prose is thrown away and the plain template goes out
instead.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta

import pytest

from app.core.config import settings
from app.models.drivers import Driver
from app.models.driver_app import DriverExpense
from app.models.enums import ExpenseCategory, TripStatus
from app.models.maintenance import FuelLog
from app.models.organizations import Organization
from app.models.owner_alerts import AlertKind, AlertSeverity, TelegramAccount
from app.models.trips import Trip
from app.models.trucks import Truck
from app.services.owner_alerts import briefing, bus
from app.services.owner_alerts.briefing import (
    BriefingFacts,
    build_alert,
    build_prompt,
    collect,
    compose_with_ai,
    render_plain,
    run,
    unverified_numbers,
)
from app.services.period_reports import report_tz
from app.services.telegram import SendResult


def _facts(**kwargs) -> BriefingFacts:
    base = dict(
        org_id=uuid.uuid4(),
        org_name="Silk Road Logistics",
        day=date(2026, 9, 2),
        delivered_trips=3,
        delivered_revenue=45_000_000,
        on_the_road=5,
        distance_km=1_240.4,
        fuel_liters=820.0,
        fuel_cost=9_840_000,
        expense_cost=1_200_000,
        unauthorized_stops=2,
        idle_hours=3.5,
        overdue_items=1,
        expiring_soon=4,
    )
    base.update(kwargs)
    return BriefingFacts(**base)


# ── The templated digest ─────────────────────────────────────────────────


def test_the_template_alone_is_a_complete_digest():
    """No API key is the default deployment, so this path is the product.

    It has to carry every figure by itself — an owner without an AI key still
    gets their morning numbers, only without the prose around them.
    """
    lines = render_plain(_facts())
    assert len(lines) == 5
    body = "\n".join(lines)
    for figure in _facts().figures():
        assert figure.text in body


def test_a_quiet_night_still_reports_its_zeros():
    """A fleet that did nothing must read as "0 ta", not as a missing line.

    Hiding empty figures would make the digest silently shorter on exactly the
    mornings an owner most needs to notice that nothing moved.
    """
    lines = render_plain(
        _facts(
            delivered_trips=0,
            delivered_revenue=0,
            on_the_road=0,
            distance_km=0,
            fuel_liters=0,
            fuel_cost=0,
            expense_cost=0,
            unauthorized_stops=0,
            idle_hours=0,
            overdue_items=0,
            expiring_soon=0,
        )
    )
    assert len(lines) == 5
    assert "<b>0 ta</b> yetkazildi" in lines[0]
    assert "<b>0 km</b>" in lines[1]


def test_money_is_grouped_the_way_it_is_written_on_an_invoice():
    lines = render_plain(_facts(delivered_revenue=45_000_000))
    assert "45 000 000 so'm" in lines[0]


# ── What the model is shown ──────────────────────────────────────────────


def test_every_figure_reaches_the_prompt():
    """The model can only phrase what it was given; anything absent it invents."""
    _, user = build_prompt(_facts())
    for figure in _facts().figures():
        assert figure.text in user


def test_the_prompt_never_names_the_company():
    """A fleet called "Fleet 24" would put a stray 24 in the prose.

    The verifier cannot tell that digit apart from a fabricated litre count, so
    it would reject an otherwise perfect answer. Keeping the name out of the
    prompt is cheaper than teaching the verifier about names.
    """
    system, user = build_prompt(_facts(org_name="Fleet 24"))
    assert "Fleet 24" not in user + system


# ── The verifier ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "written,expected",
    [
        ("45 000 000", 45_000_000.0),
        ("45000000", 45_000_000.0),
        ("1,200,000", 1_200_000.0),
        ("1.200.000", 1_200_000.0),
        ("3.5", 3.5),
        ("3,5", 3.5),
        ("0", 0.0),
    ],
)
def test_a_number_is_recognised_however_the_model_spaced_it(written, expected):
    """Models group thousands however they please; all of it is the same figure."""
    assert briefing._to_number(written) == expected


def test_numbers_copied_from_the_figures_all_pass():
    facts = _facts()
    text = "Kecha 3 ta reys yetkazildi, daromad 45 000 000 so'm. Yo'lda 5 ta mashina."
    assert unverified_numbers(text, facts.figures()) == []


def test_a_figure_the_model_derived_is_caught():
    """The dangerous case is not a wild number, it is a plausible one.

    45 000 000 minus 9 840 000 is arithmetic we never did and cannot stand
    behind. It has to fail the gate exactly as a hallucination would.
    """
    facts = _facts()
    assert unverified_numbers("Sof foyda 35 160 000 so'm.", facts.figures()) == ["35 160 000"]


def test_a_rounded_figure_is_still_a_different_number():
    """"Roughly 1 200 km" is not the 1 240 km we measured."""
    facts = _facts(distance_km=1_240.4)
    assert unverified_numbers("Taxminan 1 200 km.", facts.figures()) == ["1 200"]


def test_a_percentage_the_model_computed_is_caught():
    facts = _facts()
    assert unverified_numbers("Marja 22 foiz.", facts.figures()) == ["22"]


def test_prose_without_any_number_is_not_suspicious():
    assert unverified_numbers("Hammasi joyida, katta muammo yo'q.", _facts().figures()) == []


# ── The model path ───────────────────────────────────────────────────────


@pytest.fixture
def ai_key(monkeypatch):
    monkeypatch.setattr(settings, "ai_api_key", "test-key", raising=False)


def _answer(monkeypatch, text: str) -> list[str]:
    calls: list[str] = []

    async def _fake(system: str, user: str) -> str:
        calls.append(user)
        return text

    monkeypatch.setattr(briefing, "call_chat_completion", _fake)
    return calls


async def test_without_a_key_the_model_is_never_reached(monkeypatch):
    """Empty AI_API_KEY is the default, so this must not cost an HTTP attempt."""
    monkeypatch.setattr(settings, "ai_api_key", "", raising=False)
    calls = _answer(monkeypatch, "should not be used")
    assert await compose_with_ai(_facts()) is None
    assert calls == []


async def test_verified_prose_is_used_and_escaped(monkeypatch, ai_key):
    """The model writes text, not markup — a stray tag must not reach Telegram."""
    _answer(
        monkeypatch,
        "Kecha 3 ta reys yetkazildi.\n"
        "Yo'lda 5 ta mashina bor.\n"
        "Xarajat & daromad muvozanatda.\n"
        "<b>Xayrli tong</b>.\n"
        "Nazorat davom etmoqda.",
    )
    lines = await compose_with_ai(_facts())
    assert lines is not None
    assert "&amp;" in lines[2]
    assert "&lt;b&gt;" in lines[3]
    # Apostrophes survive: "yo'lda" escaped into "yo&#x27;lda" is unreadable.
    assert "Yo'lda" in lines[1]


async def test_an_invented_number_throws_the_whole_answer_away(monkeypatch, ai_key):
    """Not the offending line — the answer.

    A digest that keeps four measured lines and drops the fifth is a digest the
    owner cannot tell apart from a complete one, and the missing line is the
    only clue that the model was making things up.
    """
    _answer(
        monkeypatch,
        "Kecha 3 ta reys yetkazildi.\nYoqilg'i 999 l quyildi.\nYo'lda 5 ta mashina.",
    )
    assert await compose_with_ai(_facts()) is None


async def test_a_provider_failure_never_reaches_the_caller(monkeypatch, ai_key):
    """This runs inside a scheduler tick shared with every other watcher."""

    async def _boom(system: str, user: str) -> str:
        raise RuntimeError("provider is down")

    monkeypatch.setattr(briefing, "call_chat_completion", _boom)
    assert await compose_with_ai(_facts()) is None


async def test_a_one_line_answer_is_not_a_digest(monkeypatch, ai_key):
    """A truncated answer looks like a broken product, so prefer the template."""
    _answer(monkeypatch, "Kecha 3 ta reys yetkazildi.")
    assert await compose_with_ai(_facts()) is None


# ── The alert ────────────────────────────────────────────────────────────


def test_the_alert_is_keyed_on_the_day_it_summarises():
    """The scheduler ticks four times inside the delivery window.

    Dedupe on the date is the only thing between that and four identical
    briefings landing before breakfast.
    """
    alert = build_alert(_facts(day=date(2026, 9, 2)), ["bir", "ikki"])
    assert alert.dedupe_key == "briefing:2026-09-02"
    assert alert.kind is AlertKind.briefing


@pytest.mark.parametrize(
    "hour,expected",
    [
        (7, True),   # the target hour itself
        (9, True),   # a worker restarted late still owes the owner a briefing
        (12, True),  # last hour of the catch-up window
        (13, False), # by afternoon the digest is stale, not late
        (6, False),  # before the owner asked for it
        (0, False),
    ],
)
def test_the_window_opens_at_the_target_hour_and_closes_six_hours_later(
    monkeypatch, hour, expected
):
    """Delivery is a window, not an instant, and that is deliberate.

    A chat still inside its quiet hours at 07:00 is *deferred* by the bus
    without a dedupe row, so a gate that only opened on one exact hour would
    drop that owner's briefing entirely. The window lets the next tick finish
    the job. It does not wrap past midnight, because the day being summarised
    would change halfway through it.
    """
    monkeypatch.setattr(briefing, "briefing_hour", lambda: 7)
    now = datetime.now(report_tz()).replace(hour=hour)
    assert briefing._in_window(now) is expected


def test_a_typo_in_the_configured_hour_falls_back_instead_of_silencing_the_digest(
    monkeypatch,
):
    """An out-of-range hour must not mean "never", and must not raise in a tick."""
    monkeypatch.delattr(settings, "briefing_hour_local", raising=False)
    monkeypatch.setenv("BRIEFING_HOUR_LOCAL", "99")
    assert briefing.briefing_hour() == briefing.DEFAULT_BRIEFING_HOUR
    monkeypatch.setenv("BRIEFING_HOUR_LOCAL", "ertalab")
    assert briefing.briefing_hour() == briefing.DEFAULT_BRIEFING_HOUR
    monkeypatch.setenv("BRIEFING_HOUR_LOCAL", "6")
    assert briefing.briefing_hour() == 6


def test_the_briefing_outranks_a_new_chats_default_filter():
    """A fresh chat starts at min_severity=warning.

    An ``info`` briefing would therefore be dropped by every default install —
    the one message meant to build the habit would be the one nobody receives.
    """
    alert = build_alert(_facts(), ["bir"])
    assert alert.severity is AlertSeverity.warning


# ── Facts, against a real database ───────────────────────────────────────


@pytest.fixture
def captured_sends(monkeypatch) -> list[tuple[str, str]]:
    """Switch the feature gate on and capture what would have been sent."""
    monkeypatch.setattr(settings, "telegram_bot_token", "TEST:token", raising=False)
    monkeypatch.setattr(settings, "ai_api_key", "", raising=False)
    sends: list[tuple[str, str]] = []

    async def _fake_send(chat_id, text, *, disable_notification=False):
        sends.append((chat_id, text))
        return SendResult(ok=True, status_code=200)

    monkeypatch.setattr(bus, "send_message", _fake_send)
    return sends


@pytest.fixture
def now_is_briefing_time(monkeypatch) -> None:
    """Pretend the configured hour is whatever hour the test is running in."""
    monkeypatch.setattr(briefing, "briefing_hour", lambda: datetime.now(report_tz()).hour)


def _yesterday() -> date:
    return datetime.now(report_tz()).date() - timedelta(days=1)


def _local(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute), tzinfo=report_tz())


async def _org(db, name: str = "Alert Co", *, chat: bool = True, active: bool = True):
    org = Organization(name=name, is_active=active)
    db.add(org)
    await db.flush()
    if chat:
        db.add(
            TelegramAccount(
                org_id=org.id,
                token=uuid.uuid4().hex,
                chat_id=f"chat-{uuid.uuid4().hex[:8]}",
                min_severity=AlertSeverity.warning,
                muted_kinds=[],
                quiet_from_hour=None,
                quiet_to_hour=None,
            )
        )
    await db.commit()
    return org


async def _truck(db, org) -> Truck:
    truck = Truck(org_id=org.id, name="Truck", plate_number=f"P-{uuid.uuid4().hex[:8]}")
    db.add(truck)
    await db.flush()
    return truck


async def test_the_day_measured_is_the_owners_day_not_a_utc_one(db):
    """The load-bearing arithmetic in this module.

    Tashkent is UTC+5, so a fill at 23:30 last night and one at 00:30 this
    morning land on the *same* UTC date. A digest built on UTC days would put
    this morning's fill into "kecha" and overstate the owner's fuel bill every
    single day.
    """
    org = await _org(db)
    truck = await _truck(db, org)
    day = _yesterday()
    db.add_all(
        [
            FuelLog(
                truck_id=truck.id,
                liters=100,
                cost_per_liter=10_000,
                total_cost=1_000_000,
                filled_at=_local(day, 23, 30),
            ),
            FuelLog(
                truck_id=truck.id,
                liters=999,
                cost_per_liter=10_000,
                total_cost=9_990_000,
                filled_at=_local(day + timedelta(days=1), 0, 30),
            ),
        ]
    )
    await db.commit()

    facts = await collect(db, org.id, day)
    assert facts.fuel_liters == 100
    assert facts.fuel_cost == 1_000_000


async def test_revenue_counts_the_trips_delivered_yesterday(db):
    """Revenue is earned on delivery — that is when the freight was done."""
    org = await _org(db)
    day = _yesterday()
    db.add_all(
        [
            Trip(
                org_id=org.id,
                reference="TR-1",
                status=TripStatus.delivered,
                rate=20_000_000,
                delivered_at=_local(day, 10),
            ),
            Trip(
                org_id=org.id,
                reference="TR-2",
                status=TripStatus.delivered,
                rate=5_000_000,
                delivered_at=_local(day - timedelta(days=3), 10),
            ),
            Trip(org_id=org.id, reference="TR-3", status=TripStatus.en_route, rate=7_000_000),
            Trip(org_id=org.id, reference="TR-4", status=TripStatus.planned, rate=7_000_000),
        ]
    )
    await db.commit()

    facts = await collect(db, org.id, day)
    assert facts.delivered_trips == 1
    assert facts.delivered_revenue == 20_000_000
    # "planned" has not left the yard; counting it inflates the one figure an
    # owner can check by looking out of the window.
    assert facts.on_the_road == 1


async def test_another_companys_money_never_appears(db):
    """A briefing is the easiest place to leak a tenant, because nobody audits it."""
    mine = await _org(db, "Mine")
    theirs = await _org(db, "Theirs")
    day = _yesterday()

    their_truck = await _truck(db, theirs)
    their_driver = Driver(org_id=theirs.id, name="Ular", license_number=f"L-{uuid.uuid4().hex[:6]}")
    db.add(their_driver)
    await db.flush()
    db.add_all(
        [
            Trip(
                org_id=theirs.id,
                reference="TR-X",
                status=TripStatus.delivered,
                rate=99_000_000,
                delivered_at=_local(day, 12),
            ),
            FuelLog(
                truck_id=their_truck.id,
                liters=500,
                cost_per_liter=10_000,
                total_cost=5_000_000,
                filled_at=_local(day, 12),
            ),
            DriverExpense(
                driver_id=their_driver.id,
                category=ExpenseCategory.food,
                amount=300_000,
                spent_at=day,
            ),
        ]
    )
    await db.commit()

    facts = await collect(db, mine.id, day)
    assert facts.delivered_revenue == 0
    assert facts.fuel_liters == 0
    assert facts.expense_cost == 0


async def test_driver_spending_is_counted_on_the_day_it_was_spent(db):
    org = await _org(db)
    day = _yesterday()
    driver = Driver(org_id=org.id, name="Aziz", license_number=f"L-{uuid.uuid4().hex[:6]}")
    db.add(driver)
    await db.flush()
    db.add_all(
        [
            DriverExpense(
                driver_id=driver.id, category=ExpenseCategory.food, amount=200_000, spent_at=day
            ),
            DriverExpense(
                driver_id=driver.id,
                category=ExpenseCategory.toll,
                amount=900_000,
                spent_at=day - timedelta(days=1),
            ),
        ]
    )
    await db.commit()

    facts = await collect(db, org.id, day)
    assert facts.expense_cost == 200_000


# ── The tick ─────────────────────────────────────────────────────────────


async def test_the_digest_goes_out_once_a_day(db, captured_sends, now_is_briefing_time):
    """The scheduler re-runs this every fifteen minutes. The day does not change."""
    org = await _org(db)
    assert await run(db) == 1
    assert await run(db) == 0
    assert await run(db) == 0
    assert len(captured_sends) == 1
    assert "Ertalabki xulosa" in captured_sends[0][1]


async def test_without_an_api_key_the_owner_still_gets_their_numbers(
    db, captured_sends, now_is_briefing_time
):
    """Degrading to silence would be worse than degrading to a plain template."""
    org = await _org(db)
    db.add(
        Trip(
            org_id=org.id,
            reference="TR-9",
            status=TripStatus.delivered,
            rate=12_000_000,
            delivered_at=_local(_yesterday(), 9),
        )
    )
    await db.commit()

    assert await run(db) == 1
    assert "12 000 000 so'm" in captured_sends[0][1]


async def test_nothing_is_sent_outside_the_morning_window(db, captured_sends, monkeypatch):
    """A "morning" digest arriving at 19:00 is just an interruption."""
    await _org(db)
    monkeypatch.setattr(
        briefing, "briefing_hour", lambda: (datetime.now(report_tz()).hour + 8) % 24
    )
    assert await run(db) == 0
    assert captured_sends == []


async def test_a_suspended_customer_stops_receiving_their_numbers(
    db, captured_sends, now_is_briefing_time
):
    """Suspension locks a customer out of the panel; the bot must follow.

    Otherwise an unpaid invoice buys the fleet a daily operations report for
    free through a channel nobody thinks to switch off.
    """
    await _org(db, "Unpaid", active=False)
    assert await run(db) == 0
    assert captured_sends == []


async def test_an_org_nobody_linked_a_chat_to_is_never_scanned(
    db, captured_sends, now_is_briefing_time, monkeypatch
):
    """Collecting facts means a GPS scan; doing it for nobody is pure waste."""
    await _org(db, "Silent", chat=False)
    scanned: list[uuid.UUID] = []
    original = briefing.collect

    async def _spy(session, org_id, day):
        scanned.append(org_id)
        return await original(session, org_id, day)

    monkeypatch.setattr(briefing, "collect", _spy)
    assert await run(db) == 0
    assert scanned == []


async def test_one_broken_organization_does_not_end_the_sweep(
    db, captured_sends, now_is_briefing_time, monkeypatch
):
    """Every other customer's briefing must survive one customer's bad data."""
    await _org(db)

    async def _boom(session, org_id, day):
        raise ValueError("bad row")

    monkeypatch.setattr(briefing, "collect", _boom)
    assert await run(db) == 0  # and, crucially, no exception into the tick


async def test_a_disabled_bot_makes_the_job_a_no_op(db, monkeypatch):
    """No token means no Telegram at all — not a scan of every organization."""
    monkeypatch.setattr(settings, "telegram_bot_token", "", raising=False)
    await _org(db)
    assert await run(db) == 0
