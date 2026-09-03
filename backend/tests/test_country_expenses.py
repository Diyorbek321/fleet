"""Country-expense report — "where did this truck's money go on this run".

What is actually at risk here is not arithmetic but *meaning*: three currencies
that must never be added together, an exchange rate that may or may not exist,
and a fuel table that lives outside the expense grid but is the biggest number
in it. Most of what follows pins those three down.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from httpx import AsyncClient

from app.models.enums import TripReportCountry, TripReportExpenseCategory
from app.models.organizations import Organization
from app.models.trip_reports import TripCountryExpenseLine, TripExpenseReport, TripFuelRow
from app.models.trips import Trip
from app.services.country_expenses import (
    FUEL_CATEGORY,
    INSURANCE_CATEGORY,
    aggregate,
    build_trip_row,
    default_range,
    resolve_rates,
)


def _org(**rates) -> Organization:
    return Organization(name="Test Org", **rates)


def _trip(**kwargs) -> Trip:
    defaults = dict(reference="TR-1", created_at=datetime(2026, 8, 10, tzinfo=timezone.utc))
    return Trip(**{**defaults, **kwargs})


def _report(**kwargs) -> TripExpenseReport:
    """A report detached from any session, with its child collections primed.

    Setting them explicitly matters: ``build_trip_row`` iterates both, and on a
    transient ORM object an untouched relationship is not an empty list.
    """
    report = TripExpenseReport(**kwargs)
    report.fuel_rows = []
    report.country_expenses = []
    return report


def _with_lines(report: TripExpenseReport, *, fuel=None, expenses=None) -> TripExpenseReport:
    report.fuel_rows = fuel or []
    report.country_expenses = expenses or []
    return report


def _line(country: str, category: str, amount: float) -> TripCountryExpenseLine:
    return TripCountryExpenseLine(
        country=TripReportCountry(country),
        category=TripReportExpenseCategory(category),
        amount=amount,
    )


def _block(row, country: str):
    return next(b for b in row.countries if b.country == country)


def _line_of(block, category: str):
    return next(l for l in block.lines if l.category == category)


# ── Exchange rates ────────────────────────────────────────────────────────


class TestRates:
    def test_trip_own_exchange_wins_over_the_org_rate(self):
        """The rate this trip actually got beats any configured average.

        The driver handed over 100 dollars and came back with 52 000 tenge;
        that is what the money on this trip was worth, spread and all.
        """
        report = _report(usd_to_kzt_given=100, usd_to_kzt_received=52000)
        rates = resolve_rates(report, _org(usd_to_kzt=480))
        assert rates.kzt == 520
        assert rates.kzt_source == "trip"

    def test_org_rate_fills_in_when_the_trip_exchanged_nothing(self):
        rates = resolve_rates(_report(), _org(usd_to_kzt=480, usd_to_rub=80))
        assert (rates.kzt, rates.kzt_source) == (480, "org")
        assert (rates.rub, rates.rub_source) == (80, "org")

    def test_half_filled_exchange_row_is_not_a_rate(self):
        """Dollars handed over with nothing recorded back says nothing.

        Treating it as a rate would divide by zero or invent one from a single
        side of a transaction.
        """
        rates = resolve_rates(_report(usd_to_kzt_given=100), _org())
        assert rates.kzt is None
        assert rates.kzt_source is None

    def test_no_rate_anywhere_stays_none_rather_than_guessing(self):
        rates = resolve_rates(_report(), _org())
        assert (rates.kzt, rates.rub, rates.uzs) == (None, None, None)

    def test_som_has_no_trip_level_source(self):
        """The form never records a dollars-to-so'm exchange, so UZS is org-only."""
        report = _report(usd_to_kzt_given=100, usd_to_kzt_received=52000)
        rates = resolve_rates(report, _org(usd_to_uzs=12600))
        assert (rates.uzs, rates.uzs_source) == (12600, "org")


# ── One trip, three countries ─────────────────────────────────────────────


class TestTripRow:
    def _full_trip(self):
        report = _with_lines(
            _report(
                usd_to_kzt_given=100,
                usd_to_kzt_received=52000,
                usd_to_rub_given=100,
                usd_to_rub_received=8000,
                insurance_kz=5200,
                insurance_rf=1600,
                odometer_out=100_000,
                odometer_in=106_400,
            ),
            fuel=[
                TripFuelRow(row_no=1, kz_liters=300, kz_amount=104_000, rf_liters=200, rf_amount=16_000),
                TripFuelRow(row_no=2, doha_liters=150, doha_amount=180),
            ],
            expenses=[
                _line("kz", "platon", 26_000),
                _line("kz", "food", 5_200),
                _line("ru", "platon", 8_000),
                _line("uz", "taxi", 126_000),
            ],
        )
        return build_trip_row(_trip(), report, _org(usd_to_uzs=12600), truck_plate="01A123BC")

    def test_each_country_keeps_its_own_currency(self):
        row = self._full_trip()
        assert [b.currency for b in row.countries] == ["UZS", "KZT", "RUB"]

    def test_fuel_is_folded_into_the_country_it_was_bought_in(self):
        """Diesel is the biggest line of the trip and must not sit outside it."""
        row = self._full_trip()
        kz = _block(row, "kz")
        fuel = _line_of(kz, FUEL_CATEGORY)
        assert (fuel.amount, fuel.liters) == (104_000, 300)
        assert _line_of(_block(row, "ru"), FUEL_CATEGORY).amount == 16_000
        assert kz.fuel_liters == 300

    def test_card_fuel_is_reported_apart_from_any_country(self):
        """DOHA/E1 are settled centrally — putting them in a country invents a fact."""
        row = self._full_trip()
        assert [(c.column, c.liters, c.amount) for c in row.cards] == [("doha", 150, 180)]
        for block in row.countries:
            assert all(l.category != "doha" for l in block.lines)

    def test_insurance_joins_its_country_as_a_normal_line(self):
        row = self._full_trip()
        assert _line_of(_block(row, "kz"), INSURANCE_CATEGORY).amount == 5_200
        assert _line_of(_block(row, "ru"), INSURANCE_CATEGORY).amount == 1_600

    def test_country_total_is_native_and_usd_is_derived(self):
        row = self._full_trip()
        kz = _block(row, "kz")
        # 104 000 fuel + 26 000 platon + 5 200 food + 5 200 insurance.
        assert kz.total == 140_400
        assert kz.total_usd == 270.0  # at 520 KZT/USD
        assert kz.rate_source == "trip"

    def test_only_usd_is_added_across_countries(self):
        row = self._full_trip()
        # KZ 270 + RU (25 600 / 80 = 320) + UZ (126 000 / 12 600 = 10).
        assert row.total_usd == 600.0
        assert row.usd_partial is False

    def test_lines_are_ordered_by_what_cost_most(self):
        row = self._full_trip()
        amounts = [l.amount for l in _block(row, "kz").lines]
        assert amounts == sorted(amounts, reverse=True)
        assert _block(row, "kz").lines[0].category == FUEL_CATEGORY

    def test_missing_rate_empties_usd_without_zeroing_the_spend(self):
        """A blank USD column means "not converted", never "cost nothing"."""
        report = _with_lines(_report(), expenses=[_line("kz", "platon", 26_000)])
        row = build_trip_row(_trip(), report, _org())
        kz = _block(row, "kz")
        assert kz.total == 26_000
        assert kz.total_usd is None
        assert _line_of(kz, "platon").amount_usd is None
        assert row.usd_partial is True
        assert row.total_usd is None

    def test_partial_rates_flag_the_total_as_incomplete(self):
        """One country converted and another not must not read as a full total."""
        report = _with_lines(
            _report(usd_to_kzt_given=100, usd_to_kzt_received=52000),
            expenses=[_line("kz", "platon", 26_000), _line("ru", "platon", 8_000)],
        )
        row = build_trip_row(_trip(), report, _org())
        assert row.total_usd == 50.0
        assert row.usd_partial is True

    def test_distance_prefers_the_odometer_the_driver_wrote_down(self):
        row = self._full_trip()
        assert row.distance_km == 6_400

    def test_distance_falls_back_to_the_planned_figure(self):
        report = _with_lines(_report(), expenses=[_line("uz", "taxi", 100)])
        row = build_trip_row(_trip(planned_distance_km=5_000), report, _org())
        assert row.distance_km == 5_000

    def test_form_names_override_the_fleet_record(self):
        """A paper form can name a substitute driver; that is the truth for this trip."""
        report = _with_lines(
            _report(driver_name="Substitute Driver", plate_number="01Z999ZZ"),
            expenses=[_line("uz", "taxi", 100)],
        )
        row = build_trip_row(
            _trip(), report, _org(), truck_plate="01A123BC", driver_name="Regular Driver"
        )
        assert row.driver_name == "Substitute Driver"
        assert row.plate_number == "01Z999ZZ"


# ── Rolling several trips up ──────────────────────────────────────────────


class TestAggregate:
    def test_native_sums_per_country_and_usd_across_them(self):
        rows = [
            build_trip_row(
                _trip(),
                _with_lines(
                    _report(usd_to_kzt_given=100, usd_to_kzt_received=50_000),
                    expenses=[_line("kz", "platon", 25_000)],
                ),
                _org(),
            ),
            build_trip_row(
                _trip(),
                _with_lines(
                    _report(usd_to_kzt_given=100, usd_to_kzt_received=52_000),
                    expenses=[_line("kz", "platon", 26_000)],
                ),
                _org(),
            ),
        ]
        blocks, _cards, total_usd, partial, missing = aggregate(rows)
        kz = next(b for b in blocks if b.country == "kz")
        assert kz.total == 51_000  # tenge, summed within one currency
        assert kz.total_usd == 100.0  # 50 + 50, each at its own trip's rate
        assert total_usd == 100.0
        assert (partial, missing) == (False, [])

    def test_differing_rates_report_the_effective_one_as_mixed(self):
        """Neither trip's rate is the answer, so the weighted one is shown and labelled."""
        rows = [
            build_trip_row(
                _trip(),
                _with_lines(
                    _report(usd_to_kzt_given=100, usd_to_kzt_received=50_000),
                    expenses=[_line("kz", "platon", 25_000)],
                ),
                _org(),
            ),
            build_trip_row(
                _trip(),
                _with_lines(_report(), expenses=[_line("kz", "platon", 24_000)]),
                _org(usd_to_kzt=480),
            ),
        ]
        blocks, *_ = aggregate(rows)
        kz = next(b for b in blocks if b.country == "kz")
        assert kz.rate_source == "mixed"
        assert kz.rate == 490.0  # 49 000 tenge over 100 USD
        # Lines are restated at the effective rate so they add up to the total.
        assert sum(l.amount_usd for l in kz.lines) == kz.total_usd

    def test_a_half_converted_country_shows_no_rate_at_all(self):
        """total / total_usd is not a rate when only some trips converted.

        It divides *all* the spending by the converted part, so it comes out
        far too high — and restating the lines from it would inflate the USD
        column past what was actually convertible. The block reports no rate
        and is flagged partial instead.
        """
        rows = [
            build_trip_row(
                _trip(),
                _with_lines(
                    _report(usd_to_kzt_given=100, usd_to_kzt_received=52_000),
                    expenses=[_line("kz", "platon", 26_000)],
                ),
                _org(),
            ),
            build_trip_row(
                _trip(), _with_lines(_report(), expenses=[_line("kz", "platon", 26_000)]), _org()
            ),
        ]
        blocks, _cards, total_usd, partial, missing = aggregate(rows)
        kz = next(b for b in blocks if b.country == "kz")
        assert kz.total == 52_000
        # Only the converted half reaches USD, and no rate is offered.
        assert kz.total_usd == 50.0
        assert kz.rate is None
        assert total_usd == 50.0
        assert (partial, missing) == (True, ["kz"])

    def test_a_country_with_no_rate_is_named_so_it_can_be_fixed(self):
        rows = [
            build_trip_row(
                _trip(), _with_lines(_report(), expenses=[_line("ru", "platon", 8_000)]), _org()
            )
        ]
        _blocks, _cards, total_usd, partial, missing = aggregate(rows)
        assert total_usd is None
        assert partial is True
        assert missing == ["ru"]

    def test_card_fuel_sums_across_trips(self):
        rows = [
            build_trip_row(
                _trip(),
                _with_lines(_report(), fuel=[TripFuelRow(row_no=1, doha_liters=100, doha_amount=120)]),
                _org(),
            ),
            build_trip_row(
                _trip(),
                _with_lines(_report(), fuel=[TripFuelRow(row_no=1, doha_liters=50, doha_amount=60)]),
                _org(),
            ),
        ]
        _blocks, cards, *_ = aggregate(rows)
        assert [(c.column, c.liters, c.amount) for c in cards] == [("doha", 150, 180)]


def test_default_range_is_a_closed_window_ending_today():
    start, end = default_range(date(2026, 9, 3))
    assert end == date(2026, 9, 3)
    assert (end - start).days == 89


# ── Endpoints ─────────────────────────────────────────────────────────────


async def _trip_with_report(client: AsyncClient, admin_headers, driver_login, **report) -> str:
    trip = await client.post(
        "/api/trips",
        headers=admin_headers,
        json={"shipper": "Tashkent Agro", "rate": 5_000_000, "driver_id": driver_login["driver_id"]},
    )
    assert trip.status_code == 200, trip.text
    trip_id = trip.json()["id"]
    saved = await client.put(
        f"/api/me/trips/{trip_id}/report", headers=driver_login["headers"], json=report
    )
    assert saved.status_code == 200, saved.text
    return trip_id


async def test_report_splits_a_trip_by_country(client: AsyncClient, admin_headers, driver_login):
    await _trip_with_report(
        client,
        admin_headers,
        driver_login,
        plate_number="01A123BC",
        usd_to_kzt_given=100,
        usd_to_kzt_received=52_000,
        fuel_rows=[{"row_no": 1, "kz_liters": 300, "kz_amount": 104_000}],
        country_expenses=[
            {"country": "kz", "category": "platon", "amount": 26_000},
            {"country": "uz", "category": "taxi", "amount": 100_000},
        ],
    )

    res = await client.get("/api/reports/country-expenses", headers=admin_headers)
    assert res.status_code == 200, res.text
    body = res.json()

    assert len(body["trips"]) == 1
    kz = next(b for b in body["countries"] if b["country"] == "kz")
    assert kz["currency"] == "KZT"
    assert kz["total"] == 130_000
    assert kz["total_usd"] == 250.0
    assert {l["category"] for l in kz["lines"]} == {"fuel", "platon"}
    # No so'm rate configured, so the Uzbek leg stays native-only and says so.
    assert body["countries_missing_rate"] == ["uz"]
    assert body["usd_partial"] is True


async def test_trips_without_a_filled_form_are_left_out(client: AsyncClient, admin_headers, driver_login):
    """A row of empty columns reads as "this trip cost nothing" — it does not."""
    await client.post(
        "/api/trips",
        headers=admin_headers,
        json={"shipper": "No Report Co", "rate": 1_000_000, "driver_id": driver_login["driver_id"]},
    )
    res = await client.get("/api/reports/country-expenses", headers=admin_headers)
    assert res.json()["trips"] == []


async def test_truck_filter_narrows_to_one_lorry(client: AsyncClient, admin_headers, driver_login):
    truck = await client.post(
        "/api/trucks",
        headers=admin_headers,
        json={"name": "Volvo 1", "plate_number": "01A555BC"},
    )
    assert truck.status_code in (200, 201), truck.text
    truck_id = truck.json()["id"]

    trip = await client.post(
        "/api/trips",
        headers=admin_headers,
        json={"shipper": "A", "rate": 1, "driver_id": driver_login["driver_id"], "truck_id": truck_id},
    )
    await client.put(
        f"/api/me/trips/{trip.json()['id']}/report",
        headers=driver_login["headers"],
        json={"country_expenses": [{"country": "kz", "category": "platon", "amount": 1_000}]},
    )
    await _trip_with_report(
        client, admin_headers, driver_login,
        country_expenses=[{"country": "ru", "category": "platon", "amount": 500}],
    )

    both = await client.get("/api/reports/country-expenses", headers=admin_headers)
    assert len(both.json()["trips"]) == 2

    one = await client.get(
        f"/api/reports/country-expenses?truck_id={truck_id}", headers=admin_headers
    )
    assert len(one.json()["trips"]) == 1
    assert one.json()["trips"][0]["plate_number"] == "01A555BC"


async def test_range_outside_the_trip_returns_nothing(client: AsyncClient, admin_headers, driver_login):
    await _trip_with_report(
        client, admin_headers, driver_login,
        country_expenses=[{"country": "kz", "category": "platon", "amount": 1_000}],
    )
    old = (date.today() - timedelta(days=400)).isoformat()
    older = (date.today() - timedelta(days=430)).isoformat()
    res = await client.get(
        f"/api/reports/country-expenses?from={older}&to={old}", headers=admin_headers
    )
    assert res.json()["trips"] == []


async def test_backwards_range_is_rejected(client: AsyncClient, admin_headers):
    res = await client.get(
        "/api/reports/country-expenses?from=2026-08-31&to=2026-08-01", headers=admin_headers
    )
    assert res.status_code == 422


async def test_org_rate_feeds_the_report(client: AsyncClient, admin_headers, driver_login):
    await client.put("/api/org/settings", headers=admin_headers, json={"usd_to_uzs": 12_600})
    await _trip_with_report(
        client, admin_headers, driver_login,
        country_expenses=[{"country": "uz", "category": "taxi", "amount": 126_000}],
    )
    body = (await client.get("/api/reports/country-expenses", headers=admin_headers)).json()
    uz = next(b for b in body["countries"] if b["country"] == "uz")
    assert uz["total_usd"] == 10.0
    assert uz["rate_source"] == "org"
    assert body["countries_missing_rate"] == []


async def test_xlsx_download_is_a_spreadsheet(client: AsyncClient, admin_headers, driver_login):
    await _trip_with_report(
        client, admin_headers, driver_login,
        country_expenses=[{"country": "kz", "category": "platon", "amount": 1_000}],
    )
    res = await client.get("/api/reports/country-expenses.xlsx", headers=admin_headers)
    assert res.status_code == 200
    assert res.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml"
    )
    assert "reys-xarajatlari" in res.headers["content-disposition"]
    assert res.content[:2] == b"PK"  # a zip, which is what xlsx is


# ── Organization settings ─────────────────────────────────────────────────


async def test_rates_start_empty_and_round_trip(client: AsyncClient, admin_headers):
    before = await client.get("/api/org/settings", headers=admin_headers)
    assert before.json()["usd_to_kzt"] is None

    saved = await client.put(
        "/api/org/settings",
        headers=admin_headers,
        json={"usd_to_kzt": 520, "usd_to_rub": 80, "usd_to_uzs": 12_600},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["usd_to_kzt"] == 520

    assert (await client.get("/api/org/settings", headers=admin_headers)).json()["usd_to_rub"] == 80


async def test_null_clears_a_rate(client: AsyncClient, admin_headers):
    """Clearing is a real intent — back to native amounts only."""
    await client.put("/api/org/settings", headers=admin_headers, json={"usd_to_kzt": 520})
    cleared = await client.put("/api/org/settings", headers=admin_headers, json={"usd_to_kzt": None})
    assert cleared.json()["usd_to_kzt"] is None


async def test_a_non_positive_rate_is_refused(client: AsyncClient, admin_headers):
    res = await client.put("/api/org/settings", headers=admin_headers, json={"usd_to_kzt": 0})
    assert res.status_code == 422


async def test_operators_may_read_the_rates_but_not_change_them(
    client: AsyncClient, admin_headers, operator_headers
):
    assert (await client.get("/api/org/settings", headers=operator_headers)).status_code == 200
    res = await client.put("/api/org/settings", headers=operator_headers, json={"usd_to_kzt": 1})
    assert res.status_code == 403
