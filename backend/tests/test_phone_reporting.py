"""What the driver's phone sends besides a position.

* **Buffered points.** With no signal on the steppe the phone keeps its fixes
  and sends them in one batch when the network is back, so the truck's track
  has no hole — and an old batch must not move the truck back on the map.
* **Its own state.** Battery, whether it may track in the background, and the
  app version, so "no signal" on the panel comes with a reason.
* **The minimum version.** APKs are passed around by hand; the app asks the
  server which version it must at least be.
* **A wake-up.** A silent phone gets a data-only push that restarts tracking.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.models.driver_app import PushToken
from app.models.trucks import TruckLocation, TruckLocationHistory
from app.services import phone_wake, push


async def _assigned(client: AsyncClient, admin_headers, driver_login) -> str:
    truck = (
        await client.post("/api/trucks", headers=admin_headers, json={"name": "T", "plate_number": "PH-01"})
    ).json()
    res = await client.post(
        f"/api/drivers/{driver_login['driver_id']}/assign",
        headers=admin_headers,
        json={"truck_id": truck["id"]},
    )
    assert res.status_code in (200, 201), res.text
    return truck["id"]


def _at(minutes_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()


async def test_a_buffered_batch_lands_in_the_history_in_order(
    client: AsyncClient, admin_headers, driver_login, db
):
    truck_id = await _assigned(client, admin_headers, driver_login)
    points = [
        {"latitude": 43.0 + i / 10, "longitude": 68.0, "recorded_at": _at(60 - i * 10)}
        for i in range(5)
    ]
    res = await client.post("/api/me/locations", headers=driver_login["headers"], json={"points": points})
    assert res.status_code == 200, res.text
    assert res.json()["accepted"] == 5

    history = (
        await db.execute(
            select(TruckLocationHistory)
            .where(TruckLocationHistory.truck_id == uuid.UUID(truck_id))
            .order_by(TruckLocationHistory.recorded_at)
        )
    ).scalars().all()
    assert [round(float(h.latitude), 1) for h in history] == [43.0, 43.1, 43.2, 43.3, 43.4]
    latest = (await db.execute(select(TruckLocation).where(TruckLocation.truck_id == uuid.UUID(truck_id)))).scalar_one()
    assert round(float(latest.latitude), 1) == 43.4


async def test_an_old_batch_does_not_move_the_truck_back(
    client: AsyncClient, admin_headers, driver_login, db
):
    truck_id = await _assigned(client, admin_headers, driver_login)
    h = driver_login["headers"]
    await client.post("/api/me/location", headers=h, json={"latitude": 50.0, "longitude": 60.0, "recorded_at": _at(1)})
    await client.post(
        "/api/me/locations", headers=h,
        json={"points": [{"latitude": 40.0, "longitude": 60.0, "recorded_at": _at(90)}]},
    )

    latest = (await db.execute(select(TruckLocation).where(TruckLocation.truck_id == uuid.UUID(truck_id)))).scalar_one()
    await db.refresh(latest)
    assert round(float(latest.latitude), 1) == 50.0


async def test_the_batch_is_sorted_whatever_order_it_arrives_in(
    client: AsyncClient, admin_headers, driver_login, db
):
    truck_id = await _assigned(client, admin_headers, driver_login)
    points = [
        {"latitude": 41.0, "longitude": 60.0, "recorded_at": _at(5)},
        {"latitude": 42.0, "longitude": 60.0, "recorded_at": _at(30)},
    ]
    await client.post("/api/me/locations", headers=driver_login["headers"], json={"points": points})
    latest = (await db.execute(select(TruckLocation).where(TruckLocation.truck_id == uuid.UUID(truck_id)))).scalar_one()
    assert round(float(latest.latitude), 1) == 41.0


async def test_an_oversized_batch_is_refused(client: AsyncClient, admin_headers, driver_login):
    await _assigned(client, admin_headers, driver_login)
    points = [{"latitude": 41.0, "longitude": 60.0}] * 1001
    res = await client.post("/api/me/locations", headers=driver_login["headers"], json={"points": points})
    assert res.status_code == 422


async def test_the_phone_state_reaches_the_signal_panel(
    client: AsyncClient, admin_headers, driver_login
):
    truck_id = await _assigned(client, admin_headers, driver_login)
    await client.post(
        "/api/me/location",
        headers=driver_login["headers"],
        json={
            "latitude": 41.3, "longitude": 69.2,
            "battery": 0.12, "tracking": "foreground", "app_version": "0.5.0",
        },
    )
    rows = {r["truck_id"]: r for r in (await client.get("/api/trucks/signal", headers=admin_headers)).json()}
    row = rows[truck_id]
    assert row["phone_battery"] == pytest.approx(0.12)
    assert row["phone_tracking"] == "foreground"
    assert row["phone_app_version"] == "0.5.0"


async def test_a_ping_without_phone_state_keeps_the_last_one(
    client: AsyncClient, admin_headers, driver_login
):
    """An older APK sends no state; that must not wipe what a newer one said."""
    truck_id = await _assigned(client, admin_headers, driver_login)
    h = driver_login["headers"]
    await client.post("/api/me/location", headers=h, json={"latitude": 41.3, "longitude": 69.2, "app_version": "0.5.0"})
    await client.post("/api/me/location", headers=h, json={"latitude": 41.4, "longitude": 69.2})
    rows = {r["truck_id"]: r for r in (await client.get("/api/trucks/signal", headers=admin_headers)).json()}
    assert rows[truck_id]["phone_app_version"] == "0.5.0"


async def test_the_app_learns_the_minimum_version(client: AsyncClient, monkeypatch):
    monkeypatch.setattr(settings, "driver_app_min_version", "0.5.0")
    monkeypatch.setattr(settings, "driver_app_latest_version", "0.5.1")
    monkeypatch.setattr(settings, "driver_app_download_url", "https://fleet.eduly.uz/app.apk")
    # Public: an app too old to sign in must still be able to ask.
    res = await client.get("/api/app/driver-version")
    assert res.status_code == 200
    assert res.json() == {
        "min_version": "0.5.0",
        "latest_version": "0.5.1",
        "download_url": "https://fleet.eduly.uz/app.apk",
    }


# ── Wake-up ──────────────────────────────────────────────────────────────


@pytest.fixture
def silent_pushes(monkeypatch) -> list[dict]:
    sent: list[dict] = []

    async def _fake(db, tokens, *, title, body, data=None, transport=None, silent=False):
        sent.append({"tokens": [t.token for t in tokens], "data": data, "silent": silent})
        return push.PushOutcome(accepted=len(tokens))

    monkeypatch.setattr(push, "send_to_tokens", _fake)
    return sent


async def _with_token(db, driver_login) -> None:
    from app.models.users import User

    user = (
        await db.execute(select(User).where(User.driver_id == uuid.UUID(driver_login["driver_id"])))
    ).scalar_one()
    db.add(PushToken(user_id=user.id, token="fcm-token-1", platform="android"))
    await db.commit()


async def test_a_silent_phone_is_woken_with_a_data_only_push(
    client: AsyncClient, admin_headers, driver_login, db, silent_pushes
):
    truck_id = await _assigned(client, admin_headers, driver_login)
    await _with_token(db, driver_login)
    db.add(TruckLocation(truck_id=uuid.UUID(truck_id), latitude=41.0, longitude=69.0,
                         recorded_at=datetime.now(timezone.utc) - timedelta(hours=2)))
    await db.commit()

    assert await phone_wake.run(db) == 1
    assert silent_pushes[0]["silent"] is True
    assert silent_pushes[0]["data"] == {"kind": "wake"}


async def test_a_reporting_phone_is_left_alone(
    client: AsyncClient, admin_headers, driver_login, db, silent_pushes
):
    await _assigned(client, admin_headers, driver_login)
    await _with_token(db, driver_login)
    await client.post("/api/me/location", headers=driver_login["headers"], json={"latitude": 41.3, "longitude": 69.2})

    assert await phone_wake.run(db) == 0
    assert silent_pushes == []


async def test_a_phone_silent_for_days_is_not_woken_forever(
    client: AsyncClient, admin_headers, driver_login, db, silent_pushes
):
    """Switched off or thrown in a drawer: a push every tick for weeks helps no one."""
    truck_id = await _assigned(client, admin_headers, driver_login)
    await _with_token(db, driver_login)
    db.add(TruckLocation(truck_id=uuid.UUID(truck_id), latitude=41.0, longitude=69.0,
                         recorded_at=datetime.now(timezone.utc) - timedelta(days=5)))
    await db.commit()

    assert await phone_wake.run(db) == 0


async def test_a_resent_buffer_is_not_recorded_twice(
    client: AsyncClient, admin_headers, driver_login, db
):
    """The request arrived, the answer was lost, the phone sent it again."""
    truck_id = await _assigned(client, admin_headers, driver_login)
    points = [{"latitude": 43.0 + i / 10, "longitude": 68.0, "recorded_at": _at(60 - i * 10)} for i in range(3)]
    for _ in range(2):
        await client.post("/api/me/locations", headers=driver_login["headers"], json={"points": points})

    history = (
        await db.execute(select(TruckLocationHistory).where(TruckLocationHistory.truck_id == uuid.UUID(truck_id)))
    ).scalars().all()
    assert len(history) == 3


async def test_an_old_buffer_raises_no_geofence_events(
    client: AsyncClient, admin_headers, driver_login, db
):
    """Replayed against where the truck is now, it would announce a false exit."""
    from app.models.geofences import GeofenceEvent

    await _assigned(client, admin_headers, driver_login)
    res = await client.post(
        "/api/geofences", headers=admin_headers,
        json={"name": "Depot", "center_lat": 41.0, "center_lng": 69.0, "radius_m": 1000},
    )
    assert res.status_code in (200, 201), res.text
    h = driver_login["headers"]
    await client.post("/api/me/location", headers=h, json={"latitude": 41.0, "longitude": 69.0, "recorded_at": _at(1)})
    before = len((await db.execute(select(GeofenceEvent))).scalars().all())

    await client.post(
        "/api/me/locations", headers=h,
        json={"points": [{"latitude": 45.0, "longitude": 69.0, "recorded_at": _at(120)},
                         {"latitude": 45.1, "longitude": 69.0, "recorded_at": _at(110)}]},
    )
    after = len((await db.execute(select(GeofenceEvent))).scalars().all())
    assert after == before


# ── A phone whose clock is wrong ─────────────────────────────────────────


async def _latest(db, truck_id: str) -> TruckLocation:
    loc = (await db.execute(select(TruckLocation).where(TruckLocation.truck_id == uuid.UUID(truck_id)))).scalar_one()
    await db.refresh(loc)
    return loc


async def test_a_phone_clock_hours_ahead_is_corrected(client: AsyncClient, admin_headers, driver_login, db):
    """Left uncorrected, its fixes sit in the future and freeze the marker."""
    truck_id = await _assigned(client, admin_headers, driver_login)
    ahead = timedelta(hours=3)
    phone_now = datetime.now(timezone.utc) + ahead
    await client.post(
        "/api/me/locations", headers=driver_login["headers"],
        json={"sent_at": phone_now.isoformat(),
              "points": [{"latitude": 41.0, "longitude": 69.0, "recorded_at": (phone_now - timedelta(minutes=10)).isoformat()}]},
    )
    loc = await _latest(db, truck_id)
    expected = datetime.now(timezone.utc) - timedelta(minutes=10)
    assert abs((loc.recorded_at - expected).total_seconds()) < 60


async def test_a_phone_clock_behind_is_corrected(client: AsyncClient, admin_headers, driver_login):
    """Left uncorrected, a live truck reads as silent for hours."""
    truck_id = await _assigned(client, admin_headers, driver_login)
    phone_now = datetime.now(timezone.utc) - timedelta(hours=2)
    await client.post(
        "/api/me/locations", headers=driver_login["headers"],
        json={"sent_at": phone_now.isoformat(),
              "points": [{"latitude": 41.0, "longitude": 69.0, "recorded_at": phone_now.isoformat()}]},
    )
    rows = {r["truck_id"]: r for r in (await client.get("/api/trucks/signal", headers=admin_headers)).json()}
    assert rows[truck_id]["state"] == "ok"


async def test_a_small_drift_is_left_alone(client: AsyncClient, admin_headers, driver_login, db):
    truck_id = await _assigned(client, admin_headers, driver_login)
    fix_at = datetime.now(timezone.utc) - timedelta(minutes=20)
    await client.post(
        "/api/me/locations", headers=driver_login["headers"],
        json={"sent_at": (datetime.now(timezone.utc) + timedelta(seconds=40)).isoformat(),
              "points": [{"latitude": 41.0, "longitude": 69.0, "recorded_at": fix_at.isoformat()}]},
    )
    loc = await _latest(db, truck_id)
    assert abs((loc.recorded_at - fix_at).total_seconds()) < 1


async def test_a_future_fix_without_the_phone_clock_is_capped_at_now(
    client: AsyncClient, admin_headers, driver_login, db
):
    """An older client sends no sent_at; a fix from the future still must not freeze the map."""
    truck_id = await _assigned(client, admin_headers, driver_login)
    await client.post(
        "/api/me/location", headers=driver_login["headers"],
        json={"latitude": 41.0, "longitude": 69.0, "recorded_at": _at(-300)},
    )
    loc = await _latest(db, truck_id)
    assert loc.recorded_at <= datetime.now(timezone.utc) + timedelta(seconds=5)


async def test_a_resent_buffer_from_a_wrong_clock_is_still_recorded_once(
    client: AsyncClient, admin_headers, driver_login, db
):
    """Each retry measures the skew a few seconds differently; the fixes must
    still land on the same corrected times, or the dedupe misses them."""
    truck_id = await _assigned(client, admin_headers, driver_login)
    stamp = (datetime.now(timezone.utc) + timedelta(hours=3) - timedelta(minutes=30)).isoformat()
    for jitter in (0, 7):
        sent = datetime.now(timezone.utc) + timedelta(hours=3, seconds=jitter)
        await client.post(
            "/api/me/locations", headers=driver_login["headers"],
            json={"sent_at": sent.isoformat(), "points": [{"latitude": 41.0, "longitude": 69.0, "recorded_at": stamp}]},
        )
    history = (
        await db.execute(select(TruckLocationHistory).where(TruckLocationHistory.truck_id == uuid.UUID(truck_id)))
    ).scalars().all()
    assert len(history) == 1
