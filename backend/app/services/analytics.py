"""Leakage analytics — the money-first layer.

Turns raw location history + fuel logs + geofences into the three things a
mid-size fleet owner actually loses money on:

1. Fuel waste — trucks burning more litres per 100 km than the fleet baseline.
2. Unauthorized stops — long stops outside any known depot/customer geofence
   (the classic side-job / siphoning signature).
3. Idle burn — engine-on-but-not-moving time outside authorized locations.

All computation is plain Python + haversine so it runs identically on Postgres
and the SQLite test DB (no PostGIS dependency).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import TripStatus
from app.models.geofences import Geofence
from app.models.maintenance import FuelLog
from app.models.trips import Trip
from app.models.trucks import Truck, TruckLocationHistory

EARTH_RADIUS_KM = 6371.0

# Tuning knobs (conservative defaults; surfaced so they can be moved to config).
EFFICIENCY_FLAG_RATIO = 1.30      # >130% of fleet baseline L/100km = flagged
MIN_STOP_MINUTES = 25             # a stop must last this long to count
STOP_SPEED_KMH = 5.0              # at/below this we treat the truck as stopped
MIN_KM_FOR_EFFICIENCY = 50.0      # ignore trucks with too little distance to judge

# Fuel-fraud (per fill-up) knobs.
MAX_TANK_LITERS = 1000.0          # a single fill above this can't fit one truck → siphoning/jerrycans
PRICE_OUTLIER_RATIO = 1.25        # cost/litre >125% of the truck's median = inflated receipt
EXCESS_CONSUMPTION_L_PER_100 = 80.0  # implied burn between fills above this is implausible


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


@dataclass
class _TruckTrack:
    distance_km: float = 0.0
    points: list = field(default_factory=list)  # (recorded_at, lat, lng, speed)


async def _load_tracks(db: AsyncSession, start: datetime, end: datetime, org_id) -> dict[str, _TruckTrack]:
    stmt = (
        select(TruckLocationHistory)
        .join(Truck, Truck.id == TruckLocationHistory.truck_id)
        .where(
            TruckLocationHistory.recorded_at >= start,
            TruckLocationHistory.recorded_at <= end,
            Truck.org_id == org_id,
        )
        .order_by(TruckLocationHistory.truck_id, TruckLocationHistory.recorded_at)
    )
    tracks: dict[str, _TruckTrack] = {}
    prev_tid = None
    prev_lat = prev_lon = None
    for row in (await db.execute(stmt)).scalars():
        tid = str(row.truck_id)
        track = tracks.setdefault(tid, _TruckTrack())
        lat, lon = float(row.latitude), float(row.longitude)
        if tid == prev_tid and prev_lat is not None:
            track.distance_km += _haversine_km(prev_lat, prev_lon, lat, lon)
        track.points.append((row.recorded_at, lat, lon, float(row.speed or 0)))
        prev_tid, prev_lat, prev_lon = tid, lat, lon
    return tracks


def _point_in_any_fence(lat: float, lon: float, fences: list[tuple[float, float, float]]) -> bool:
    for flat, flon, radius_m in fences:
        if _haversine_km(lat, lon, flat, flon) * 1000.0 <= radius_m:
            return True
    return False


async def fuel_anomalies(db: AsyncSession, days: int, org_id) -> dict:
    """Per-truck fuel efficiency vs. fleet baseline; flags + estimated waste cost."""
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    tracks = await _load_tracks(db, start, end, org_id)

    # Fuel litres + spend per truck in the window (this org only).
    fuel_rows = (
        await db.execute(
            select(
                FuelLog.truck_id,
                func.coalesce(func.sum(FuelLog.liters), 0),
                func.coalesce(func.sum(FuelLog.total_cost), 0),
            )
            .join(Truck, Truck.id == FuelLog.truck_id)
            .where(FuelLog.filled_at >= start, Truck.org_id == org_id)
            .group_by(FuelLog.truck_id)
        )
    ).all()
    fuel_by_truck = {str(tid): (float(litres), float(cost)) for tid, litres, cost in fuel_rows}

    trucks = {str(t.id): t for t in (await db.execute(select(Truck).where(Truck.org_id == org_id))).scalars().all()}

    rows = []
    efficiencies = []
    for tid, (litres, cost) in fuel_by_truck.items():
        track = tracks.get(tid)
        dist = track.distance_km if track else 0.0
        if dist < MIN_KM_FOR_EFFICIENCY or litres <= 0:
            continue
        l_per_100 = litres / dist * 100.0
        efficiencies.append(l_per_100)
        rows.append({"truck_id": tid, "distance_km": dist, "liters": litres, "cost": cost, "l_per_100km": l_per_100})

    baseline = sorted(efficiencies)[len(efficiencies) // 2] if efficiencies else 0.0  # median

    anomalies = []
    total_waste_cost = 0.0
    for r in rows:
        flagged = baseline > 0 and r["l_per_100km"] > baseline * EFFICIENCY_FLAG_RATIO
        waste_cost = 0.0
        if flagged:
            expected_litres = baseline * r["distance_km"] / 100.0
            waste_litres = max(r["liters"] - expected_litres, 0.0)
            cost_per_litre = r["cost"] / r["liters"] if r["liters"] else 0.0
            waste_cost = waste_litres * cost_per_litre
            total_waste_cost += waste_cost
        t = trucks.get(r["truck_id"])
        anomalies.append(
            {
                "truck_id": r["truck_id"],
                "truck_name": t.name if t else "—",
                "plate_number": t.plate_number if t else "—",
                "distance_km": round(r["distance_km"], 1),
                "liters": round(r["liters"], 1),
                "l_per_100km": round(r["l_per_100km"], 1),
                "baseline_l_per_100km": round(baseline, 1),
                "flagged": flagged,
                "estimated_waste_cost": round(waste_cost, 2),
            }
        )
    anomalies.sort(key=lambda x: (not x["flagged"], -x["estimated_waste_cost"]))
    return {
        "baseline_l_per_100km": round(baseline, 1),
        "flagged_count": sum(1 for a in anomalies if a["flagged"]),
        "estimated_waste_cost": round(total_waste_cost, 2),
        "trucks": anomalies,
    }


async def unauthorized_stops(db: AsyncSession, days: int, org_id) -> dict:
    """Stops longer than MIN_STOP_MINUTES outside every active geofence."""
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    tracks = await _load_tracks(db, start, end, org_id)

    fences = [
        (float(f.center_lat), float(f.center_lng), float(f.radius_m))
        for f in (
            await db.execute(
                select(Geofence).where(Geofence.active.is_(True), Geofence.org_id == org_id)
            )
        ).scalars().all()
    ]
    trucks = {str(t.id): t for t in (await db.execute(select(Truck).where(Truck.org_id == org_id))).scalars().all()}

    stops = []
    total_idle_minutes = 0.0
    for tid, track in tracks.items():
        i = 0
        pts = track.points
        n = len(pts)
        while i < n:
            ts0, lat0, lon0, spd0 = pts[i]
            if spd0 > STOP_SPEED_KMH:
                i += 1
                continue
            j = i
            while j + 1 < n and pts[j + 1][3] <= STOP_SPEED_KMH:
                j += 1
            ts_start, ts_end = pts[i][0], pts[j][0]
            duration_min = (ts_end - ts_start).total_seconds() / 60.0
            if duration_min >= MIN_STOP_MINUTES:
                total_idle_minutes += duration_min
                if not _point_in_any_fence(lat0, lon0, fences):
                    t = trucks.get(tid)
                    stops.append(
                        {
                            "truck_id": tid,
                            "truck_name": t.name if t else "—",
                            "plate_number": t.plate_number if t else "—",
                            "latitude": round(lat0, 5),
                            "longitude": round(lon0, 5),
                            "started_at": ts_start,
                            "ended_at": ts_end,
                            "duration_minutes": round(duration_min, 1),
                        }
                    )
            i = j + 1

    stops.sort(key=lambda x: x["duration_minutes"], reverse=True)
    return {
        "unauthorized_stop_count": len(stops),
        "total_idle_hours": round(total_idle_minutes / 60.0, 1),
        "stops": stops,
    }


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2.0


async def fuel_fraud_events(db: AsyncSession, days: int, org_id) -> dict:
    """Flag individual suspicious fuel fill-ups (the direct theft signal).

    Unlike :func:`fuel_anomalies` (which compares each truck's average efficiency
    to the fleet baseline), this looks at each fill-up and flags concrete red
    flags an owner can act on:

    * **oversized_fill** — more litres than a tank physically holds.
    * **price_outlier** — cost/litre well above the truck's own median (inflated
      or forged receipt).
    * **excess_consumption** — litres bought vs. odometer distance since the
      previous fill imply an impossible burn rate.

    Heuristic and conservative by design — every event is a *prompt to check the
    receipt/CCTV*, not a conviction.
    """
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)

    rows = (
        await db.execute(
            select(FuelLog, Truck.name, Truck.plate_number)
            .join(Truck, Truck.id == FuelLog.truck_id)
            .where(FuelLog.filled_at >= start, Truck.org_id == org_id)
            .order_by(FuelLog.truck_id, FuelLog.filled_at)
        )
    ).all()

    # Per-truck median cost/litre for the price-outlier check.
    prices_by_truck: dict[str, list[float]] = {}
    for log, _name, _plate in rows:
        prices_by_truck.setdefault(str(log.truck_id), []).append(float(log.cost_per_liter or 0))
    median_price = {tid: _median(ps) for tid, ps in prices_by_truck.items()}

    events: list[dict] = []
    total_suspicious_cost = 0.0
    prev_tid = None
    prev_mileage = None

    for log, name, plate in rows:
        tid = str(log.truck_id)
        liters = float(log.liters or 0)
        price = float(log.cost_per_liter or 0)
        cost = float(log.total_cost or 0)
        mileage = float(log.mileage_at_fill) if log.mileage_at_fill is not None else None

        reasons: list[str] = []

        if liters > MAX_TANK_LITERS:
            reasons.append("oversized_fill")

        med = median_price.get(tid, 0.0)
        if med > 0 and price > med * PRICE_OUTLIER_RATIO:
            reasons.append("price_outlier")

        if tid == prev_tid and prev_mileage is not None and mileage is not None:
            dist = mileage - prev_mileage
            if dist > 1:
                implied = liters / dist * 100.0
                if implied > EXCESS_CONSUMPTION_L_PER_100:
                    reasons.append("excess_consumption")
            elif dist <= 1 and liters > 50:
                # bought a lot of fuel but the odometer barely moved
                reasons.append("excess_consumption")

        if reasons:
            total_suspicious_cost += cost
            events.append(
                {
                    "fuel_log_id": str(log.id),
                    "truck_id": tid,
                    "truck_name": name,
                    "plate_number": plate,
                    "filled_at": log.filled_at,
                    "liters": round(liters, 1),
                    "cost_per_liter": round(price, 2),
                    "total_cost": round(cost, 2),
                    "fuel_station": log.fuel_station,
                    "reasons": reasons,
                }
            )

        prev_tid, prev_mileage = tid, mileage

    events.sort(key=lambda e: e["total_cost"], reverse=True)
    return {
        "window_days": days,
        "flagged_count": len(events),
        "total_suspicious_cost": round(total_suspicious_cost, 2),
        "events": events,
    }


async def leakage_summary(db: AsyncSession, days: int, org_id) -> dict:
    """Top-line money view: what leaked, and the trip-level health behind it."""
    fuel = await fuel_anomalies(db, days, org_id)
    stops = await unauthorized_stops(db, days, org_id)

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)

    active_trips = (
        await db.execute(
            select(func.count(Trip.id)).where(
                Trip.org_id == org_id,
                Trip.status.in_([TripStatus.planned, TripStatus.loading, TripStatus.en_route, TripStatus.at_border]),
            )
        )
    ).scalar() or 0
    delivered_trips = (
        await db.execute(
            select(func.count(Trip.id)).where(
                Trip.org_id == org_id, Trip.status == TripStatus.delivered, Trip.delivered_at >= start
            )
        )
    ).scalar() or 0

    return {
        "window_days": days,
        "estimated_fuel_waste_cost": fuel["estimated_waste_cost"],
        "flagged_trucks": fuel["flagged_count"],
        "fuel_baseline_l_per_100km": fuel["baseline_l_per_100km"],
        "unauthorized_stop_count": stops["unauthorized_stop_count"],
        "total_idle_hours": stops["total_idle_hours"],
        "active_trips": int(active_trips),
        "delivered_trips": int(delivered_trips),
    }
