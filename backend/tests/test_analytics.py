"""Leakage analytics: the streaming GPS scan and the window it is honest about.

These cover the two things that make the money layer trustworthy:

* the scan folds millions of position rows into per-truck aggregates *without*
  materialising them, and does so correctly across truck boundaries;
* a requested window is clamped to the period raw GPS is actually retained, so
  a fuel total is never divided by a truncated distance total.

GPS history is seeded through the ORM rather than the ingest endpoint because
ingest always stamps "now" — every case here needs backdated points.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.geofences import Geofence
from app.models.trucks import Truck, TruckLocationHistory
from app.services.analytics import (
    MIN_STOP_MINUTES,
    effective_window_days,
    scan_tracks,
    unauthorized_stops,
)

# Tashkent-ish. One degree of longitude here is ~83.9 km; the tests only rely on
# "moved a lot" vs "did not move", never on an exact figure.
BASE_LAT = 41.31
BASE_LNG = 69.24


async def _signup(client: AsyncClient, email: str, org_name: str) -> dict[str, str]:
    await client.post(
        "/api/auth/register",
        json={"email": email, "password": "password123", "org_name": org_name},
    )
    login = await client.post(
        "/api/auth/login", json={"email": email, "password": "password123"}
    )
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def _create_truck(client: AsyncClient, headers: dict, plate: str) -> str:
    res = await client.post(
        "/api/trucks", headers=headers, json={"name": f"Truck {plate}", "plate_number": plate}
    )
    assert res.status_code == 200, res.text
    return res.json()["id"]


async def _org_id_of(db: AsyncSession, truck_id: str) -> uuid.UUID:
    return (
        await db.execute(select(Truck.org_id).where(Truck.id == uuid.UUID(truck_id)))
    ).scalar_one()


async def _add_points(
    db: AsyncSession,
    truck_id: str,
    points: list[tuple[datetime, float, float, float]],
) -> None:
    """points: (recorded_at, lat, lng, speed_kmh)."""
    for recorded_at, lat, lng, speed in points:
        db.add(
            TruckLocationHistory(
                truck_id=uuid.UUID(truck_id),
                latitude=lat,
                longitude=lng,
                speed=speed,
                recorded_at=recorded_at,
            )
        )
    await db.commit()


def _drive(start: datetime, minutes: int, step_min: int = 5) -> list[tuple]:
    """A moving track: one point every ``step_min`` minutes, drifting east."""
    return [
        (
            start + timedelta(minutes=i * step_min),
            BASE_LAT,
            BASE_LNG + 0.01 * i,
            60.0,
        )
        for i in range(minutes // step_min + 1)
    ]


def _park(start: datetime, minutes: int, lat: float, lng: float, step_min: int = 5) -> list[tuple]:
    """A stationary track: same coordinates, speed 0."""
    return [
        (start + timedelta(minutes=i * step_min), lat, lng, 0.0)
        for i in range(minutes // step_min + 1)
    ]


# --- the streaming scan ------------------------------------------------------


async def test_scan_accumulates_distance_and_detects_a_long_stop(
    client: AsyncClient, admin_headers, db: AsyncSession
):
    truck_id = await _create_truck(client, admin_headers, "SCAN-01")
    org_id = await _org_id_of(db, truck_id)

    now = datetime.now(timezone.utc)
    start = now - timedelta(hours=6)
    drive = _drive(start, minutes=60)
    # Park where the drive ended, so the assertion measures the driven distance
    # and not a teleport to an unrelated parking spot.
    last_at, _, last_lng, _ = drive[-1]
    await _add_points(
        db, truck_id, drive + _park(last_at + timedelta(minutes=5), 40, BASE_LAT, last_lng)
    )

    tracks = await scan_tracks(db, now - timedelta(days=1), now, org_id)

    track = tracks[truck_id]
    # 12 eastward hops of 0.01 degrees; one degree of longitude at 41.31°N is
    # ~83.6 km, so ~10 km driven.
    assert track.distance_km == pytest.approx(10.0, rel=0.15)
    assert len(track.stops) == 1
    assert track.stops[0].duration_minutes == pytest.approx(40.0, abs=0.1)


async def test_stop_shorter_than_the_threshold_is_not_recorded(
    client: AsyncClient, admin_headers, db: AsyncSession
):
    truck_id = await _create_truck(client, admin_headers, "SCAN-02")
    org_id = await _org_id_of(db, truck_id)

    now = datetime.now(timezone.utc)
    short = MIN_STOP_MINUTES - 10
    await _add_points(
        db, truck_id, _park(now - timedelta(hours=2), short, BASE_LAT, BASE_LNG)
    )

    tracks = await scan_tracks(db, now - timedelta(days=1), now, org_id)
    assert tracks[truck_id].stops == []


async def test_a_stop_at_the_end_of_a_trucks_history_is_still_emitted(
    client: AsyncClient, admin_headers, db: AsyncSession
):
    """The streaming scan's boundary case.

    A stop run is only closed when a *moving* point arrives. Two trucks whose
    histories both end parked mean the run for truck A must be closed when the
    cursor moves on to truck B, and truck B's when the stream ends. Get either
    wrong and the last stop of every truck silently disappears — or worse, A's
    run absorbs B's points and reports one impossible multi-day stop.
    """
    a_id = await _create_truck(client, admin_headers, "SCAN-03A")
    b_id = await _create_truck(client, admin_headers, "SCAN-03B")
    org_id = await _org_id_of(db, a_id)

    now = datetime.now(timezone.utc)
    await _add_points(db, a_id, _park(now - timedelta(hours=10), 45, BASE_LAT, BASE_LNG))
    await _add_points(db, b_id, _park(now - timedelta(hours=3), 35, BASE_LAT + 1, BASE_LNG))

    tracks = await scan_tracks(db, now - timedelta(days=1), now, org_id)

    assert len(tracks[a_id].stops) == 1
    assert tracks[a_id].stops[0].duration_minutes == pytest.approx(45.0, abs=0.1)
    assert len(tracks[b_id].stops) == 1
    assert tracks[b_id].stops[0].duration_minutes == pytest.approx(35.0, abs=0.1)


async def test_scan_never_returns_another_organizations_track(
    client: AsyncClient, db: AsyncSession
):
    a_headers = await _signup(client, "scan-a@org.com", "Scan Org A")
    b_headers = await _signup(client, "scan-b@org.com", "Scan Org B")

    a_truck = await _create_truck(client, a_headers, "ISO-A")
    b_truck = await _create_truck(client, b_headers, "ISO-B")
    a_org = await _org_id_of(db, a_truck)

    now = datetime.now(timezone.utc)
    await _add_points(db, a_truck, _park(now - timedelta(hours=4), 60, BASE_LAT, BASE_LNG))
    await _add_points(db, b_truck, _park(now - timedelta(hours=4), 60, BASE_LAT, BASE_LNG))

    tracks = await scan_tracks(db, now - timedelta(days=1), now, a_org)
    assert set(tracks) == {a_truck}


# --- geofence filtering ------------------------------------------------------


async def test_a_long_stop_inside_a_geofence_is_idle_but_not_unauthorized(
    client: AsyncClient, admin_headers, db: AsyncSession
):
    truck_id = await _create_truck(client, admin_headers, "FENCE-01")
    org_id = await _org_id_of(db, truck_id)

    now = datetime.now(timezone.utc)
    await _add_points(db, truck_id, _park(now - timedelta(hours=5), 60, BASE_LAT, BASE_LNG))

    db.add(
        Geofence(
            org_id=org_id,
            name="Depot",
            category="depot",
            center_lat=BASE_LAT,
            center_lng=BASE_LNG,
            radius_m=500,
            active=True,
        )
    )
    await db.commit()

    result = await unauthorized_stops(db, 7, org_id)
    assert result["unauthorized_stop_count"] == 0
    # The hour still counts as idle time — it just happened somewhere allowed.
    assert result["total_idle_hours"] == pytest.approx(1.0, abs=0.05)


# --- window clamping ---------------------------------------------------------


def test_window_is_clamped_to_the_gps_retention_period(monkeypatch):
    """The correctness half of retention, not the performance half.

    Fuel logs are kept forever, GPS points are not. An unclamped 365-day request
    would divide a year of litres by 90 days of kilometres and report a burn rate
    four times reality — turning honest drivers into flagged thieves.
    """
    monkeypatch.setattr(settings, "gps_history_retention_days", 90)
    assert effective_window_days(365) == 90
    assert effective_window_days(30) == 30


def test_window_is_untouched_when_retention_is_disabled(monkeypatch):
    monkeypatch.setattr(settings, "gps_history_retention_days", 0)
    assert effective_window_days(365) == 365


async def test_endpoint_reports_the_window_it_actually_measured(
    client: AsyncClient, admin_headers, monkeypatch
):
    monkeypatch.setattr(settings, "gps_history_retention_days", 45)

    res = await client.get("/api/analytics/leakage-summary?days=365", headers=admin_headers)
    assert res.status_code == 200, res.text
    assert res.json()["window_days"] == 45

    res = await client.get("/api/analytics/fuel-anomalies?days=365", headers=admin_headers)
    assert res.json()["window_days"] == 45

    res = await client.get("/api/analytics/unauthorized-stops?days=365", headers=admin_headers)
    assert res.json()["window_days"] == 45
