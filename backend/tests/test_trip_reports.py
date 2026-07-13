"""Trip expense report ("yo'l varaqasi"): totals math + driver/manager endpoints."""
from __future__ import annotations

from httpx import AsyncClient

from app.models.enums import TripReportCountry, TripReportExpenseCategory
from app.models.trip_reports import TripCountryExpenseLine, TripExpenseReport, TripFuelRow
from app.services.trip_reports import compute_report_totals


# ── Pure totals math (no DB) ──────────────────────────────────────────────


def test_fuel_totals_sum_across_rows_and_columns():
    rows = [
        TripFuelRow(row_no=1, kz_liters=10, kz_amount=5000, rf_liters=5, rf_amount=2000),
        TripFuelRow(row_no=2, kz_liters=8, kz_amount=4000, doha_liters=20, doha_amount=9000),
    ]
    totals = compute_report_totals(None, rows, [])
    assert totals.fuel_by_column["kz"].liters == 18
    assert totals.fuel_by_column["kz"].amount == 9000
    assert totals.fuel_by_column["rf"].liters == 5
    assert totals.fuel_by_column["doha"].amount == 9000
    assert totals.fuel_by_column["e1card"].amount == 0
    assert totals.fuel_liters_total == 43
    assert totals.fuel_amount_total == 20000


def test_country_totals_group_by_country():
    lines = [
        TripCountryExpenseLine(country=TripReportCountry.kz, category=TripReportExpenseCategory.platon, amount=1000),
        TripCountryExpenseLine(country=TripReportCountry.kz, category=TripReportExpenseCategory.food, amount=500),
        TripCountryExpenseLine(country=TripReportCountry.uz, category=TripReportExpenseCategory.taxi, amount=200),
    ]
    totals = compute_report_totals(None, [], lines)
    assert totals.country_totals["kz"] == 1500
    assert totals.country_totals["ru"] == 0
    assert totals.country_totals["uz"] == 200


def test_currency_balances_net_issued_against_spent():
    report = TripExpenseReport(
        money_usd=100, money_kzt=50000, usd_to_kzt_given=20, usd_to_kzt_received=9000,
        dollar_return=10,
    )
    fuel_rows = [TripFuelRow(row_no=1, kz_liters=10, kz_amount=4000)]
    country_lines = [
        TripCountryExpenseLine(country=TripReportCountry.kz, category=TripReportExpenseCategory.platon, amount=1000),
    ]
    totals = compute_report_totals(report, fuel_rows, country_lines)
    # USD: 100 issued - 20 exchanged - 10 returned = 70 still unaccounted for.
    assert totals.currency_balances["usd"] == 70
    # KZT: 50000 issued + 9000 exchanged-in - 4000 fuel - 1000 country expense.
    assert totals.currency_balances["kzt"] == 54000
    assert totals.currency_balances["rub"] == 0
    assert totals.currency_balances["uzs"] == 0


# ── Driver + manager endpoints ────────────────────────────────────────────


async def _create_trip_for_driver(client: AsyncClient, admin_headers, driver_id: str) -> str:
    res = await client.post(
        "/api/trips",
        headers=admin_headers,
        json={"shipper": "Tashkent Agro", "rate": 5000000, "driver_id": driver_id},
    )
    assert res.status_code == 200, res.text
    return res.json()["id"]


async def test_report_null_before_driver_starts_it(client: AsyncClient, admin_headers, driver_login):
    trip_id = await _create_trip_for_driver(client, admin_headers, driver_login["driver_id"])

    mine = await client.get(f"/api/me/trips/{trip_id}/report", headers=driver_login["headers"])
    assert mine.status_code == 200
    assert mine.json() is None

    manager_view = await client.get(f"/api/trips/{trip_id}/report", headers=admin_headers)
    assert manager_view.status_code == 200
    assert manager_view.json() is None


async def test_driver_save_and_manager_read_back(client: AsyncClient, admin_headers, driver_login):
    trip_id = await _create_trip_for_driver(client, admin_headers, driver_login["driver_id"])
    h = driver_login["headers"]

    payload = {
        "plate_number": "01A123BC",
        "money_kzt": 50000,
        "fuel_rows": [
            {"row_no": 1, "kz_liters": 10, "kz_amount": 4000},
            {"row_no": 2, "rf_liters": 5, "rf_amount": 2500},
        ],
        "country_expenses": [
            {"country": "kz", "category": "platon", "amount": 1000},
            {"country": "uz", "category": "taxi", "amount": 200},
        ],
    }
    saved = await client.put(f"/api/me/trips/{trip_id}/report", headers=h, json=payload)
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["plate_number"] == "01A123BC"
    assert body["status"] == "draft"
    assert len(body["fuel_rows"]) == 2
    assert len(body["country_expenses"]) == 2
    assert body["totals"]["fuel_amount_total"] == 6500
    assert body["totals"]["country_totals"]["kz"] == 1000
    assert body["totals"]["country_totals"]["uz"] == 200

    # Manager sees the same data read-only.
    manager_view = await client.get(f"/api/trips/{trip_id}/report", headers=admin_headers)
    assert manager_view.status_code == 200
    assert manager_view.json()["plate_number"] == "01A123BC"

    # Re-saving replaces the child rows wholesale rather than appending.
    resaved = await client.put(
        f"/api/me/trips/{trip_id}/report",
        headers=h,
        json={**payload, "fuel_rows": [{"row_no": 1, "kz_liters": 99, "kz_amount": 1}]},
    )
    assert len(resaved.json()["fuel_rows"]) == 1


async def test_submit_marks_status_and_timestamp(client: AsyncClient, admin_headers, driver_login):
    trip_id = await _create_trip_for_driver(client, admin_headers, driver_login["driver_id"])
    h = driver_login["headers"]

    # Cannot submit before the report exists.
    assert (await client.post(f"/api/me/trips/{trip_id}/report/submit", headers=h)).status_code == 404

    await client.put(f"/api/me/trips/{trip_id}/report", headers=h, json={"plate_number": "X"})
    submitted = await client.post(f"/api/me/trips/{trip_id}/report/submit", headers=h)
    assert submitted.status_code == 200
    assert submitted.json()["status"] == "submitted"
    assert submitted.json()["submitted_at"] is not None

    # Stays editable after submission.
    edited = await client.put(f"/api/me/trips/{trip_id}/report", headers=h, json={"plate_number": "Y"})
    assert edited.status_code == 200
    assert edited.json()["plate_number"] == "Y"


async def test_driver_cannot_touch_another_drivers_trip_report(
    client: AsyncClient, admin_headers, driver_login
):
    other_driver = (
        await client.post(
            "/api/drivers", headers=admin_headers, json={"name": "Other Driver", "license_number": "LIC-200"}
        )
    ).json()
    trip_id = await _create_trip_for_driver(client, admin_headers, other_driver["id"])

    res = await client.get(f"/api/me/trips/{trip_id}/report", headers=driver_login["headers"])
    assert res.status_code == 404
    res = await client.put(
        f"/api/me/trips/{trip_id}/report", headers=driver_login["headers"], json={"plate_number": "Z"}
    )
    assert res.status_code == 404
