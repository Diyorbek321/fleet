"""The cash-mismatch watcher: which imbalances are worth an owner's attention.

Two failure modes are being defended against, and they pull in opposite
directions. Too sensitive and every honest report trips the alarm, the owner
mutes the bot in week two, and the whole alerting feature is dead. Too blunt —
one threshold shared by so'm and tenge — and four hundred dollars of missing
tenge slips under the same bar that four dollars of so'm sits above.

The dedupe tests are the other load-bearing half: the scheduler re-runs this
every fifteen minutes and a mismatch does not fix itself, so "announce once,
re-check a correction" is the difference between a useful alert and ninety-six
identical messages a day.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest

from app.core.config import settings
from app.models.enums import (
    TripReportCountry,
    TripReportExpenseCategory,
    TripReportStatus,
)
from app.models.organizations import Organization
from app.models.owner_alerts import AlertKind, AlertSeverity, TelegramAccount
from app.models.trip_reports import (
    TripCountryExpenseLine,
    TripExpenseReport,
    TripFuelRow,
)
from app.models.trips import Trip
from app.services.owner_alerts import bus
from app.services.owner_alerts.cash import (
    USD_THRESHOLD,
    build_alert,
    find_gaps,
    org_rates,
    run,
)
from app.services.telegram import SendResult

# Roughly the September 2026 street rates, so the fixtures read like real money.
RATE_UZS = 12_800.0
RATE_KZT = 460.0
RATE_RUB = 90.0


def _rates(**overrides) -> dict[str, float | None]:
    base: dict[str, float | None] = {
        "usd": 1.0,
        "uzs": RATE_UZS,
        "kzt": RATE_KZT,
        "rub": RATE_RUB,
    }
    base.update(overrides)
    return base


def _no_rates() -> dict[str, float | None]:
    return {"usd": 1.0, "uzs": None, "kzt": None, "rub": None}


# ── What counts as a mismatch ────────────────────────────────────────────


def test_a_perfectly_reconciled_report_says_nothing():
    assert find_gaps({"usd": 0.0, "rub": 0.0, "kzt": 0.0, "uzs": 0.0}, _rates()) == []


def test_a_few_thousand_som_is_rounding_and_stays_quiet():
    """The alert's survival depends on this. A driver who writes 5 000 so'm for
    a 4 800 so'm lunch has not stolen anything, and an owner pinged about it
    mutes the bot before the first real mismatch arrives."""
    assert find_gaps({"uzs": 4_000.0}, _rates()) == []


def test_several_hundred_dollars_is_never_rounding():
    gaps = find_gaps({"usd": 320.0}, _rates())
    assert [g.currency for g in gaps] == ["usd"]
    assert gaps[0].amount == 320.0


def test_the_dollar_needs_no_rate_to_be_judged():
    """An organization that has configured nothing still gets the USD case."""
    assert find_gaps({"usd": 300.0}, _no_rates())[0].usd == 300.0


def test_fifty_thousand_som_and_two_hundred_thousand_tenge_are_not_the_same_problem():
    """The reason the threshold is a dollar and not a per-currency number.

    50 000 UZS is four dollars — the change in a driver's pocket. 200 000 KZT
    is four hundred, which is a fuel stop nobody can produce a receipt for. Any
    single native threshold either fires on the first or misses the second.
    """
    gaps = find_gaps({"uzs": 50_000.0, "kzt": 200_000.0}, _rates())
    assert [g.currency for g in gaps] == ["kzt"]
    assert gaps[0].usd == pytest.approx(434.78, abs=0.01)


def test_without_a_configured_rate_each_currency_is_judged_at_its_own_size():
    """The fallback still has to tell so'm from tenge, just less precisely."""
    gaps = find_gaps({"uzs": 50_000.0, "kzt": 200_000.0}, _no_rates())
    assert [g.currency for g in gaps] == ["kzt"]
    assert gaps[0].usd is None  # nothing to convert with, so nothing is claimed


def test_a_rate_configured_for_one_currency_does_not_judge_another():
    """Rates are set one field at a time; a half-filled settings form must not
    convert roubles at the tenge rate."""
    gaps = find_gaps({"rub": 30_000.0}, _rates(rub=None))
    assert [g.currency for g in gaps] == ["rub"]
    assert gaps[0].usd is None


def test_overspending_is_flagged_as_loudly_as_leftover_cash():
    """A negative balance means money was spent that was never issued — the
    driver funded it from somewhere, and where is exactly the question."""
    gaps = find_gaps({"kzt": -300_000.0}, _rates())
    assert gaps[0].unaccounted is False
    assert gaps[0].amount == -300_000.0


def test_the_threshold_is_inclusive_at_its_own_boundary():
    exact = USD_THRESHOLD * RATE_KZT
    assert find_gaps({"kzt": exact}, _rates())
    assert find_gaps({"kzt": exact - 500}, _rates()) == []


def test_every_out_of_balance_currency_is_listed_not_just_the_worst():
    """A driver short on two currencies is two conversations, not one."""
    gaps = find_gaps({"usd": 120.0, "kzt": 200_000.0}, _rates())
    assert [g.currency for g in gaps] == ["usd", "kzt"]


def test_org_rates_ignores_a_zero_or_missing_rate():
    """A rate of 0 would divide by zero; treating it as "unset" is the only
    reading of an empty settings field that does not crash the tick."""
    org = Organization(name="X", usd_to_kzt=0, usd_to_rub=None, usd_to_uzs=RATE_UZS)
    rates = org_rates(org)
    assert rates["kzt"] is None and rates["rub"] is None
    assert rates["uzs"] == RATE_UZS
    assert rates["usd"] == 1.0


# ── The message ──────────────────────────────────────────────────────────


def _report(**kwargs) -> TripExpenseReport:
    base = dict(
        id=uuid.uuid4(),
        driver_name="Bob Haydovchi",
        plate_number="01 A 123 BC",
        updated_at=datetime(2026, 9, 2, 10, 0, tzinfo=timezone.utc),
    )
    base.update(kwargs)
    return TripExpenseReport(**base)


def _trip(**kwargs) -> Trip:
    base = dict(id=uuid.uuid4(), reference="TR-2026-0042")
    base.update(kwargs)
    return Trip(**base)


def test_the_message_names_the_currency_that_is_short():
    """An owner reading this on a phone must know which envelope to ask about
    before opening the panel."""
    gaps = find_gaps({"kzt": 200_000.0, "uzs": 900_000.0}, _rates())
    alert = build_alert(_report(), _trip(), gaps)
    assert "KZT" in alert.body and "UZS" in alert.body
    assert "TR-2026-0042" in alert.title
    assert alert.kind is AlertKind.cash_mismatch


def test_the_message_distinguishes_missing_cash_from_overspending():
    unaccounted = build_alert(_report(), _trip(), find_gaps({"kzt": 200_000.0}, _rates()))
    overspent = build_alert(_report(), _trip(), find_gaps({"kzt": -200_000.0}, _rates()))
    assert "hisobsiz qoldi" in unaccounted.body
    assert "ortiqcha sarflangan" in overspent.body


def test_a_multi_currency_mismatch_is_totalled_in_dollars():
    """Two numbers in two currencies do not answer "how bad is it"."""
    alert = build_alert(
        _report(), _trip(), find_gaps({"usd": 120.0, "kzt": 200_000.0}, _rates())
    )
    assert "Jami farq" in alert.body
    assert "555" in alert.body  # $120 + 200 000 KZT at 460


def test_a_single_currency_mismatch_is_not_totalled():
    alert = build_alert(_report(), _trip(), find_gaps({"kzt": 200_000.0}, _rates()))
    assert "Jami farq" not in alert.body


def test_the_dollar_row_is_not_converted_into_itself():
    alert = build_alert(_report(), _trip(), find_gaps({"usd": 120.0}, _rates()))
    assert "≈ $" not in alert.body


def test_a_drivers_name_cannot_inject_markup():
    """`body` is passed through as HTML by the bus and never re-escaped, so
    anything from the form has to be escaped here or nowhere."""
    alert = build_alert(
        _report(driver_name="<b>Bob</b> & Co"), _trip(), find_gaps({"usd": 120.0}, _rates())
    )
    assert "&lt;b&gt;Bob&lt;/b&gt; &amp; Co" in alert.body


def test_the_alert_links_to_the_trip_it_is_about():
    trip = _trip()
    alert = build_alert(_report(), trip, find_gaps({"usd": 120.0}, _rates()))
    assert alert.path == f"/trips/{trip.id}"


def test_a_mismatch_never_claims_to_be_critical():
    """Critical is the level that overrides quiet hours. Money already spent in
    Kazakhstan is not a reason to wake anybody at 03:00."""
    alert = build_alert(_report(), _trip(), find_gaps({"usd": 5_000.0}, _rates()))
    assert alert.severity is AlertSeverity.warning


# ── End to end, over the bus ─────────────────────────────────────────────


@pytest.fixture
def captured_sends(monkeypatch) -> list[tuple[str, str]]:
    """Replace the Telegram transport and switch the feature gate on."""
    monkeypatch.setattr(settings, "telegram_bot_token", "TEST:token", raising=False)
    sends: list[tuple[str, str]] = []

    async def _fake_send(chat_id, text, *, disable_notification=False):
        sends.append((chat_id, text))
        return SendResult(ok=True, status_code=200)

    monkeypatch.setattr(bus, "send_message", _fake_send)
    return sends


async def _org_with_chat(db, *, chat_id: str = "900001", **rates) -> Organization:
    org = Organization(name="Kassa Co", **rates)
    db.add(org)
    await db.flush()
    db.add(
        TelegramAccount(
            org_id=org.id,
            token=uuid.uuid4().hex,
            chat_id=chat_id,
            min_severity=AlertSeverity.info,
            muted_kinds=[],
            quiet_from_hour=None,  # tests must not depend on the wall clock
            quiet_to_hour=None,
        )
    )
    await db.commit()
    return org


async def _submitted_report(
    db,
    org: Organization,
    *,
    money_kzt: float = 0.0,
    money_usd: float = 0.0,
    spent_kzt: float = 0.0,
    reference: str = "TR-2026-0042",
    updated_at: datetime | None = None,
) -> tuple[Trip, TripExpenseReport]:
    """A trip whose driver was issued cash and spent some of it in Kazakhstan."""
    trip = Trip(org_id=org.id, reference=reference)
    db.add(trip)
    await db.flush()

    report = TripExpenseReport(
        org_id=org.id,
        trip_id=trip.id,
        driver_name="Bob Haydovchi",
        plate_number="01 A 123 BC",
        report_date=date(2026, 9, 1),
        money_kzt=money_kzt,
        money_usd=money_usd,
        status=TripReportStatus.submitted,
        submitted_at=datetime.now(timezone.utc),
        updated_at=updated_at or datetime.now(timezone.utc),
    )
    db.add(report)
    await db.flush()

    if spent_kzt:
        db.add(
            TripCountryExpenseLine(
                report_id=report.id,
                country=TripReportCountry.kz,
                category=TripReportExpenseCategory.platon,
                amount=spent_kzt,
            )
        )
    await db.commit()
    return trip, report


async def test_a_submitted_report_that_does_not_reconcile_reaches_the_owner(
    db, captured_sends
):
    org = await _org_with_chat(db, usd_to_kzt=RATE_KZT)
    await _submitted_report(db, org, money_kzt=500_000, spent_kzt=100_000)

    assert await run(db) == 1
    assert captured_sends[0][0] == "900001"
    assert "TR-2026-0042" in captured_sends[0][1]
    assert "KZT" in captured_sends[0][1]


async def test_a_report_whose_cash_adds_up_is_silent(db, captured_sends):
    org = await _org_with_chat(db, usd_to_kzt=RATE_KZT)
    await _submitted_report(db, org, money_kzt=500_000, spent_kzt=500_000)

    assert await run(db) == 0
    assert captured_sends == []


async def test_a_draft_is_never_judged(db, captured_sends):
    """A half-filled form does not reconcile by definition. Alerting on drafts
    teaches the owner that this alert means nothing."""
    org = await _org_with_chat(db, usd_to_kzt=RATE_KZT)
    _, report = await _submitted_report(db, org, money_kzt=500_000, spent_kzt=100_000)
    report.status = TripReportStatus.draft
    await db.commit()

    assert await run(db) == 0


async def test_fuel_bought_in_tenge_settles_the_balance(db, captured_sends):
    """The fuel table lives outside the country expense grid but is still cash
    spent in tenge — missing it would invent a mismatch on every real trip."""
    org = await _org_with_chat(db, usd_to_kzt=RATE_KZT)
    _, report = await _submitted_report(db, org, money_kzt=500_000)
    db.add(TripFuelRow(report_id=report.id, row_no=1, kz_liters=600, kz_amount=500_000))
    await db.commit()

    assert await run(db) == 0


async def test_an_unchanged_report_is_only_announced_once(db, captured_sends):
    """The scheduler runs this every fifteen minutes and the mismatch persists."""
    org = await _org_with_chat(db, usd_to_kzt=RATE_KZT)
    await _submitted_report(db, org, money_kzt=500_000, spent_kzt=100_000)

    assert await run(db) == 1
    assert await run(db) == 0
    assert await run(db) == 0
    assert len(captured_sends) == 1


async def test_a_corrected_resubmission_is_judged_again(db, captured_sends):
    """The reason the dedupe key carries `updated_at`.

    A driver who finds the receipt he forgot resubmits the form; keying on the
    report id alone would file the new numbers under the old verdict and the
    owner would never learn that it is now a different — or no — problem.
    """
    org = await _org_with_chat(db, usd_to_kzt=RATE_KZT)
    _, report = await _submitted_report(db, org, money_kzt=500_000, spent_kzt=100_000)
    assert await run(db) == 1

    report.money_kzt = 900_000  # a bigger hole, freshly submitted
    report.updated_at = datetime.now(timezone.utc) + timedelta(seconds=5)
    await db.commit()

    assert await run(db) == 1
    assert len(captured_sends) == 2


async def test_a_resubmission_that_now_balances_is_not_re_announced(db, captured_sends):
    """Re-checking a correction must be able to end in silence, not in a second
    message saying the same thing about fixed numbers."""
    org = await _org_with_chat(db, usd_to_kzt=RATE_KZT)
    _, report = await _submitted_report(db, org, money_kzt=500_000, spent_kzt=100_000)
    assert await run(db) == 1

    report.money_kzt = 100_000
    report.updated_at = datetime.now(timezone.utc) + timedelta(seconds=5)
    await db.commit()

    assert await run(db) == 0
    assert len(captured_sends) == 1


async def test_last_months_reports_are_not_dredged_up_on_the_first_tick(
    db, captured_sends
):
    """Switching the bot on must not fire a year of settled trips at an owner
    in one tick — the fastest possible way to have it muted."""
    org = await _org_with_chat(db, usd_to_kzt=RATE_KZT)
    await _submitted_report(
        db,
        org,
        money_kzt=500_000,
        spent_kzt=100_000,
        updated_at=datetime.now(timezone.utc) - timedelta(days=45),
    )

    assert await run(db) == 0


async def test_one_organizations_cash_is_never_reported_to_another(db, captured_sends):
    """The sweep reads across tenants on purpose; the boundary is re-imposed at
    the notify call, and a leak here is a leak of another customer's finances."""
    watched = await _org_with_chat(db, chat_id="900001", usd_to_kzt=RATE_KZT)
    other = Organization(name="Other Co", usd_to_kzt=RATE_KZT)
    db.add(other)
    await db.commit()

    await _submitted_report(
        db, other, money_kzt=900_000, spent_kzt=0, reference="OTHER-0001"
    )
    await _submitted_report(
        db, watched, money_kzt=500_000, spent_kzt=100_000, reference="MINE-0001"
    )

    assert await run(db) == 1
    assert len(captured_sends) == 1
    assert "MINE-0001" in captured_sends[0][1]
    assert "OTHER-0001" not in captured_sends[0][1]


async def test_each_organization_is_judged_by_its_own_rate(db, captured_sends):
    """The same 200 000 tenge is $435 at one org's rate and $20 at a rate set
    for a different currency — applying the wrong one is a false alarm or a
    missed theft."""
    org = await _org_with_chat(db, usd_to_kzt=10_000.0)  # an absurd but configured rate
    await _submitted_report(db, org, money_kzt=200_000, spent_kzt=0)

    assert await run(db) == 0


async def test_a_broken_report_does_not_stop_the_sweep(db, captured_sends, monkeypatch):
    """One malformed row must not cost every other organization its alert."""
    org = await _org_with_chat(db, usd_to_kzt=RATE_KZT)
    await _submitted_report(db, org, money_kzt=500_000, spent_kzt=100_000, reference="A-1")
    await _submitted_report(db, org, money_kzt=900_000, spent_kzt=100_000, reference="A-2")

    from app.services.owner_alerts import cash as cash_module

    calls: list[str] = []

    original = cash_module.compute_report_totals

    def _explode_on_first(report, fuel_rows, country_lines):
        calls.append(str(report.id))
        if len(calls) == 1:
            raise ValueError("malformed report")
        return original(report, fuel_rows, country_lines)

    monkeypatch.setattr(cash_module, "compute_report_totals", _explode_on_first)

    assert await run(db) == 1
    assert len(calls) == 2
