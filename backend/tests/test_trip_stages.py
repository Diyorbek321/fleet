"""The checkpoint a driver reports, and what the rest of the system makes of it.

The whole design rests on one claim: a driver picks a fine-grained stage, and
every report, alert and margin keeps reading the coarse ``TripStatus`` exactly
as it did before. These tests are that claim, written down — if a stage ever
stops setting the status it implies, the money figures go quiet rather than
wrong, which is the failure nobody notices.
"""
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.enums import TripEventType, TripStatus
from app.models.trips import Trip, TripEvent


async def _driver_trip(client: AsyncClient, admin_headers, driver_id: str) -> str:
    res = await client.post(
        "/api/trips",
        headers=admin_headers,
        json={
            "driver_id": driver_id,
            "rate": 10_000_000,
            "origin_name": "Тобольск",
            "destination_name": "Ташкент",
        },
    )
    assert res.status_code == 200, res.text
    return res.json()["id"]


async def _mark(client: AsyncClient, headers, trip_id: str, stage: str, place: str):
    return await client.post(
        f"/api/me/trips/{trip_id}/advance",
        headers=headers,
        json={"stage": stage, "stage_place": place},
    )


# ── A stage sets the status it implies ───────────────────────────────────


async def test_a_reported_stage_is_stored_with_where_it_happened(
    client: AsyncClient, admin_headers, driver_login
):
    h = driver_login["headers"]
    trip_id = await _driver_trip(client, admin_headers, driver_login["driver_id"])

    res = await _mark(client, h, trip_id, "arrived_border", "uz_kz")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["current_stage"] == "arrived_border"
    assert body["current_stage_place"] == "uz_kz"


async def test_every_stage_drives_the_coarse_status_the_reports_read(
    client: AsyncClient, admin_headers, driver_login
):
    """The compatibility guarantee. Each of these is a real transition on a
    UZ↔RU run, and each has to leave `status` at the value the owner's alerts
    and the period report already understand."""
    h = driver_login["headers"]
    expected = [
        ("arrived_loading", "uz", TripStatus.loading),
        ("loaded_waiting_docs", "uz", TripStatus.loading),
        ("docs_received_en_route", "uz", TripStatus.en_route),
        ("arrived_border", "uz_kz", TripStatus.at_border),
        ("crossed_border", "uz_kz", TripStatus.en_route),
        ("arrived_customs", "ru", TripStatus.at_border),
        ("left_customs", "ru", TripStatus.en_route),
        ("arrived_unloading", "ru", TripStatus.en_route),
        ("unloaded", "ru", TripStatus.delivered),
    ]
    for stage, place, status in expected:
        trip_id = await _driver_trip(client, admin_headers, driver_login["driver_id"])
        res = await _mark(client, h, trip_id, stage, place)
        assert res.status_code == 200, res.text
        assert res.json()["status"] == status.value, stage


async def test_unloading_still_stamps_the_delivery_the_margin_is_built_on(
    client: AsyncClient, admin_headers, driver_login
):
    """`delivered_at` is what the period report counts revenue by. A driver who
    reports "выгрузился" must move it exactly as the old button did."""
    h = driver_login["headers"]
    trip_id = await _driver_trip(client, admin_headers, driver_login["driver_id"])

    await _mark(client, h, trip_id, "unloaded", "ru")

    assert (await client.get(f"/api/trips/{trip_id}", headers=admin_headers)).json()[
        "delivered_at"
    ] is not None


# ── The loading date the customer's card prints ──────────────────────────


async def test_taking_the_load_on_board_stamps_the_loading_date(
    client: AsyncClient, admin_headers, driver_login
):
    h = driver_login["headers"]
    trip_id = await _driver_trip(client, admin_headers, driver_login["driver_id"])

    assert (await _mark(client, h, trip_id, "arrived_loading", "uz")).json()["loaded_at"] is None
    loaded = (await _mark(client, h, trip_id, "loaded_waiting_docs", "uz")).json()
    assert loaded["loaded_at"] is not None


async def test_the_loading_date_is_not_moved_by_a_second_report(
    client: AsyncClient, admin_headers, driver_login
):
    """A driver re-taps it, or reloads at a second warehouse. The customer was
    already told a date, and a card that silently changes it is worse than one
    that is slightly wrong."""
    h = driver_login["headers"]
    trip_id = await _driver_trip(client, admin_headers, driver_login["driver_id"])

    first = (await _mark(client, h, trip_id, "loaded_waiting_docs", "uz")).json()["loaded_at"]
    second = (await _mark(client, h, trip_id, "loaded_waiting_docs", "uz")).json()["loaded_at"]
    assert first == second


# ── A border happens twice ───────────────────────────────────────────────


async def test_the_two_crossings_of_one_run_are_recorded_separately(
    client: AsyncClient, admin_headers, driver_login
):
    """The reason the place is a crossing and not a country. On Tashkent–Tobolsk
    the truck reaches a border twice, and a timeline that cannot tell the two
    apart cannot answer "how long from the Russian border to customs"."""
    h = driver_login["headers"]
    trip_id = await _driver_trip(client, admin_headers, driver_login["driver_id"])

    for place in ("uz_kz", "kz_ru"):
        assert (await _mark(client, h, trip_id, "arrived_border", place)).status_code == 200
        assert (await _mark(client, h, trip_id, "crossed_border", place)).status_code == 200

    async with SessionLocal() as db:
        rows = (
            await db.execute(
                select(TripEvent.stage, TripEvent.stage_place)
                .where(TripEvent.trip_id == trip_id, TripEvent.stage.is_not(None))
                .order_by(TripEvent.recorded_at)
            )
        ).all()

    assert [(s.value, p.value) for s, p in rows] == [
        ("arrived_border", "uz_kz"),
        ("crossed_border", "uz_kz"),
        ("arrived_border", "kz_ru"),
        ("crossed_border", "kz_ru"),
    ]


async def test_clearing_a_border_is_logged_as_a_clearance_not_an_arrival(
    client: AsyncClient, admin_headers, driver_login
):
    """Both moves sit inside one coarse status change, so the event type is the
    only thing that tells the timeline which of them happened."""
    h = driver_login["headers"]
    trip_id = await _driver_trip(client, admin_headers, driver_login["driver_id"])

    await _mark(client, h, trip_id, "arrived_border", "uz_kz")
    await _mark(client, h, trip_id, "crossed_border", "uz_kz")

    async with SessionLocal() as db:
        events = (
            await db.execute(
                select(TripEvent.event)
                .where(TripEvent.trip_id == trip_id, TripEvent.stage.is_not(None))
                .order_by(TripEvent.recorded_at)
            )
        ).scalars().all()

    assert events == [TripEventType.border_arrival, TripEventType.border_clear]


# ── What the server refuses ──────────────────────────────────────────────


async def test_a_border_stage_will_not_take_a_plain_country(
    client: AsyncClient, admin_headers, driver_login
):
    """"На границе КЗ" is ambiguous on this corridor, and letting it through
    would pool two different borders into one median."""
    h = driver_login["headers"]
    trip_id = await _driver_trip(client, admin_headers, driver_login["driver_id"])

    assert (await _mark(client, h, trip_id, "arrived_border", "kz")).status_code == 422


async def test_a_country_stage_will_not_take_a_crossing(
    client: AsyncClient, admin_headers, driver_login
):
    h = driver_login["headers"]
    trip_id = await _driver_trip(client, admin_headers, driver_login["driver_id"])

    assert (await _mark(client, h, trip_id, "unloaded", "uz_kz")).status_code == 422


async def test_an_advance_with_neither_a_stage_nor_a_status_is_refused(
    client: AsyncClient, admin_headers, driver_login
):
    h = driver_login["headers"]
    trip_id = await _driver_trip(client, admin_headers, driver_login["driver_id"])

    res = await client.post(f"/api/me/trips/{trip_id}/advance", headers=h, json={})
    assert res.status_code == 422


# ── The dispatcher's old path still works ────────────────────────────────


async def test_the_panel_can_still_move_a_trip_by_status_alone(
    client: AsyncClient, admin_headers, driver_login
):
    """There is no checkpoint to report from a desk, and breaking this would
    take the panel's advance button with it."""
    trip_id = await _driver_trip(client, admin_headers, driver_login["driver_id"])

    res = await client.post(
        f"/api/trips/{trip_id}/advance",
        headers=admin_headers,
        json={"to_status": "delivered"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "delivered"

    async with SessionLocal() as db:
        trip = (await db.execute(select(Trip).where(Trip.id == trip_id))).scalar_one()
    # No stage was claimed on the trip's behalf: the dispatcher did not see one.
    assert trip.current_stage is None
