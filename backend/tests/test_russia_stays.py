"""Russia stays: written by the border checkpoint, corrected by the desk, shown
to the driver, and reminded about before the 90 days run out.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models.driver_messages import DriverMessage
from app.services import russia_stay_reminders
from app.services.period_reports import report_tz


def _today() -> date:
    return datetime.now(timezone.utc).astimezone(report_tz()).date()


async def _driver_trip(client: AsyncClient, admin_headers, driver_login, direction: str) -> str:
    res = await client.post(
        "/api/trips", headers=admin_headers,
        json={"driver_id": driver_login["driver_id"], "direction": direction},
    )
    assert res.status_code == 200, res.text
    return res.json()["id"]


async def _cross(client: AsyncClient, driver_login, trip_id: str, place: str = "kz_ru") -> None:
    res = await client.post(
        f"/api/me/trips/{trip_id}/advance", headers=driver_login["headers"],
        json={"stage": "crossed_border", "stage_place": place},
    )
    assert res.status_code == 200, res.text


def _stays_url(driver_login) -> str:
    return f"/api/drivers/{driver_login['driver_id']}/russia-stays"


async def _stays(client: AsyncClient, admin_headers, driver_login) -> dict:
    res = await client.get(_stays_url(driver_login), headers=admin_headers)
    assert res.status_code == 200, res.text
    return res.json()


# ── Written by the checkpoint ────────────────────────────────────────────


async def test_crossing_into_russia_on_an_export_opens_a_stay(
    client: AsyncClient, admin_headers, driver_login
):
    trip_id = await _driver_trip(client, admin_headers, driver_login, "uz_ru")
    await _cross(client, driver_login, trip_id)

    body = await _stays(client, admin_headers, driver_login)

    assert len(body["stays"]) == 1
    stay = body["stays"][0]
    assert stay["entered_on"] == _today().isoformat()
    assert stay["left_on"] is None
    assert stay["source"] == "auto"
    assert body["summary"]["in_russia"] is True
    assert body["summary"]["day_of_stay"] == 1


async def test_crossing_back_on_an_import_closes_it(client: AsyncClient, admin_headers, driver_login):
    out = await _driver_trip(client, admin_headers, driver_login, "uz_ru")
    await _cross(client, driver_login, out)
    back = await _driver_trip(client, admin_headers, driver_login, "ru_uz")
    await _cross(client, driver_login, back)

    body = await _stays(client, admin_headers, driver_login)

    assert body["stays"][0]["left_on"] == _today().isoformat()
    assert body["summary"]["in_russia"] is False
    assert body["summary"]["days_used"] == 1


async def test_the_uzbek_kazakh_border_is_not_russia(client: AsyncClient, admin_headers, driver_login):
    trip_id = await _driver_trip(client, admin_headers, driver_login, "uz_ru")
    await _cross(client, driver_login, trip_id, place="uz_kz")

    assert (await _stays(client, admin_headers, driver_login))["stays"] == []


async def test_marking_the_crossing_twice_does_not_open_two_stays(
    client: AsyncClient, admin_headers, driver_login
):
    trip_id = await _driver_trip(client, admin_headers, driver_login, "uz_ru")
    await _cross(client, driver_login, trip_id)
    await _cross(client, driver_login, trip_id)

    assert len((await _stays(client, admin_headers, driver_login))["stays"]) == 1


async def test_the_desk_marking_the_crossing_counts_too(client: AsyncClient, admin_headers, driver_login):
    trip_id = await _driver_trip(client, admin_headers, driver_login, "uz_ru")
    res = await client.post(f"/api/trips/{trip_id}/advance", headers=admin_headers,
                            json={"stage": "crossed_border", "stage_place": "kz_ru"})
    assert res.status_code == 200, res.text

    assert len((await _stays(client, admin_headers, driver_login))["stays"]) == 1


# ── Corrected by the desk ────────────────────────────────────────────────


async def test_the_desk_records_a_stay_the_app_missed(client: AsyncClient, admin_headers, driver_login):
    entered = _today() - timedelta(days=40)
    res = await client.post(_stays_url(driver_login), headers=admin_headers,
                            json={"entered_on": entered.isoformat(), "note": "migratsiya kartasi"})
    assert res.status_code == 201, res.text

    body = await _stays(client, admin_headers, driver_login)
    assert body["summary"]["day_of_stay"] == 41
    assert body["summary"]["must_leave_by"] == (entered + timedelta(days=89)).isoformat()
    assert body["stays"][0]["source"] == "manual"


async def test_the_desk_corrects_and_deletes_a_stay(client: AsyncClient, admin_headers, driver_login):
    stay = (await client.post(_stays_url(driver_login), headers=admin_headers,
                              json={"entered_on": (_today() - timedelta(days=5)).isoformat()})).json()

    fixed = await client.patch(f"{_stays_url(driver_login)}/{stay['id']}", headers=admin_headers,
                               json={"entered_on": (_today() - timedelta(days=7)).isoformat(),
                                     "left_on": (_today() - timedelta(days=1)).isoformat()})
    assert fixed.status_code == 200, fixed.text
    assert (await _stays(client, admin_headers, driver_login))["summary"]["days_used"] == 7

    gone = await client.delete(f"{_stays_url(driver_login)}/{stay['id']}", headers=admin_headers)
    assert gone.status_code == 204
    assert (await _stays(client, admin_headers, driver_login))["stays"] == []


@pytest.mark.parametrize(
    "payload",
    [
        {"entered_on": "2099-01-01"},                                   # in the future
        {"entered_on": "2026-10-10", "left_on": "2026-10-01"},          # left before entering
    ],
)
async def test_impossible_dates_are_refused(client: AsyncClient, admin_headers, driver_login, payload):
    res = await client.post(_stays_url(driver_login), headers=admin_headers, json=payload)
    assert res.status_code == 422, res.text


async def test_overlapping_stays_are_refused(client: AsyncClient, admin_headers, driver_login):
    base = _today() - timedelta(days=30)
    first = {"entered_on": base.isoformat(), "left_on": (base + timedelta(days=10)).isoformat()}
    assert (await client.post(_stays_url(driver_login), headers=admin_headers, json=first)).status_code == 201

    overlap = {"entered_on": (base + timedelta(days=5)).isoformat(), "left_on": (base + timedelta(days=15)).isoformat()}
    assert (await client.post(_stays_url(driver_login), headers=admin_headers, json=overlap)).status_code == 409

    open_one = {"entered_on": (base + timedelta(days=20)).isoformat()}
    assert (await client.post(_stays_url(driver_login), headers=admin_headers, json=open_one)).status_code == 201
    second_open = {"entered_on": (base + timedelta(days=25)).isoformat()}
    assert (await client.post(_stays_url(driver_login), headers=admin_headers, json=second_open)).status_code == 409


async def test_a_driver_cannot_edit_the_record(client: AsyncClient, driver_login):
    res = await client.post(_stays_url(driver_login), headers=driver_login["headers"],
                            json={"entered_on": "2026-10-01"})
    assert res.status_code == 403


# ── Shown ────────────────────────────────────────────────────────────────


async def test_the_driver_sees_their_own_count(client: AsyncClient, admin_headers, driver_login):
    await client.post(_stays_url(driver_login), headers=admin_headers,
                      json={"entered_on": (_today() - timedelta(days=46)).isoformat()})

    res = await client.get("/api/me/russia-stay", headers=driver_login["headers"])

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["in_russia"] is True
    assert body["day_of_stay"] == 47
    assert body["days_to_leave"] == 43


async def test_the_fleet_list_shows_who_is_in_russia(client: AsyncClient, admin_headers, driver_login):
    await client.post(_stays_url(driver_login), headers=admin_headers,
                      json={"entered_on": (_today() - timedelta(days=3)).isoformat()})

    res = await client.get("/api/russia-stays", headers=admin_headers)

    assert res.status_code == 200, res.text
    rows = res.json()
    assert [r["driver_id"] for r in rows] == [driver_login["driver_id"]]
    assert rows[0]["summary"]["day_of_stay"] == 4


async def test_another_company_sees_none_of_it(client: AsyncClient, admin_headers, driver_login):
    await client.post(_stays_url(driver_login), headers=admin_headers,
                      json={"entered_on": (_today() - timedelta(days=3)).isoformat()})
    await client.post("/api/auth/register",
                      json={"email": "boss@other.uz", "password": "password123", "org_name": "Other Fleet"})
    login = await client.post("/api/auth/login", json={"email": "boss@other.uz", "password": "password123"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    assert (await client.get("/api/russia-stays", headers=headers)).json() == []
    assert (await client.get(_stays_url(driver_login), headers=headers)).status_code == 404


# ── Reminded ─────────────────────────────────────────────────────────────


def _at(day: date) -> datetime:
    # 09:00 Tashkent.
    return datetime(day.year, day.month, day.day, 4, 0, tzinfo=timezone.utc)


async def test_reminders_go_at_15_7_3_days_and_daily_once_over(
    client: AsyncClient, admin_headers, driver_login, db
):
    entered = _today() - timedelta(days=200)  # far enough back to walk forward through
    await client.post(_stays_url(driver_login), headers=admin_headers, json={"entered_on": entered.isoformat()})
    last_day = entered + timedelta(days=89)

    async def sent_on(day: date) -> int:
        return await russia_stay_reminders.run(db, now=_at(day))

    assert await sent_on(last_day - timedelta(days=20)) == 0
    assert await sent_on(last_day - timedelta(days=15)) == 1
    assert await sent_on(last_day - timedelta(days=14)) == 0  # same bucket
    assert await sent_on(last_day - timedelta(days=7)) == 1
    assert await sent_on(last_day - timedelta(days=3)) == 1
    assert await sent_on(last_day + timedelta(days=1)) == 1   # over
    assert await sent_on(last_day + timedelta(days=2)) == 1   # and again the next day

    messages = (await db.execute(select(DriverMessage))).scalars().all()
    assert len(messages) == 5
    assert all(m.driver_id is not None for m in messages)


async def test_a_new_export_closes_a_stay_whose_exit_was_never_marked(
    client: AsyncClient, admin_headers, driver_login
):
    # Entered 30 days ago; the way home was never marked. Now a new export crosses in.
    await client.post(_stays_url(driver_login), headers=admin_headers,
                      json={"entered_on": (_today() - timedelta(days=30)).isoformat()})
    trip_id = await _driver_trip(client, admin_headers, driver_login, "uz_ru")
    await _cross(client, driver_login, trip_id)

    stays = (await _stays(client, admin_headers, driver_login))["stays"]

    assert len(stays) == 2
    new, old = stays  # newest first
    assert new["entered_on"] == _today().isoformat() and new["left_on"] is None
    # The exit date is unknown: closed as late as it can have been, so the
    # count errs towards more days in Russia, never fewer — and flagged.
    assert old["left_on"] == (_today() - timedelta(days=1)).isoformat()
    assert old["note"]


async def test_a_crossing_that_cannot_be_recorded_does_not_cost_the_checkpoint(
    client: AsyncClient, admin_headers, driver_login, monkeypatch
):
    from app.services import russia_stay_records

    async def _broken(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(russia_stay_records, "_open_stay", _broken)
    trip_id = await _driver_trip(client, admin_headers, driver_login, "uz_ru")
    await _cross(client, driver_login, trip_id)  # asserts 200

    trip = (await client.get(f"/api/trips/{trip_id}", headers=admin_headers)).json()
    assert trip["current_stage"] == "crossed_border"
