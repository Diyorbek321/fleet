"""Leakage analytics — the money-first layer.

Turns raw location history + fuel logs + geofences into the three things a
mid-size fleet owner actually loses money on:

1. Fuel waste — trucks burning more litres per 100 km than the fleet baseline.
2. Unauthorized stops — long stops outside any known depot/customer geofence
   (the classic side-job / siphoning signature).
3. Idle burn — engine-on-but-not-moving time outside authorized locations.

All computation is plain Python + haversine (no PostGIS dependency), but the
GPS scan is **streaming**: a fleet pinging every 15 seconds writes ~48k history
rows per day per 20 trucks, so a 30-day window is millions of rows. Nothing here
ever holds more than one batch of them in memory — see :func:`scan_tracks`.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
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

# Rows pulled from the server-side cursor per round-trip during a GPS scan.
# Bounds peak memory (this many tuples) independently of the window size.
SCAN_BATCH_ROWS = 2_000


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def effective_window_days(days: int) -> int:
    """Clamp a requested window to the period raw GPS history is actually kept.

    Two reasons, and the second one is a correctness bug, not a performance one:

    * Retention purges points older than ``GPS_HISTORY_RETENTION_DAYS``, so a
      365-day request scans a table that only holds 90 days anyway.
    * :func:`fuel_anomalies` divides *fuel logged in the window* by *distance
      driven in the window*. Fuel logs are never purged. Left unclamped, a
      365-day request would put 365 days of litres over 90 days of kilometres
      and report a burn rate ~4x reality — flagging honest drivers as thieves.

    Clamping keeps both halves of every ratio measured over the same period.
    """
    retention = settings.gps_history_retention_days
    if retention <= 0:  # retention disabled — history is complete, trust the caller
        return days
    return min(days, retention)


@dataclass
class _Stop:
    """A maximal run of consecutive points at or below ``STOP_SPEED_KMH``."""

    started_at: datetime
    ended_at: datetime
    latitude: float
    longitude: float
    duration_minutes: float


@dataclass
class TruckTrack:
    """Everything the leakage layer needs from one truck's GPS history.

    Deliberately *not* the raw points: only the distance total and the stops
    that already passed the ``MIN_STOP_MINUTES`` threshold survive the scan.
    A truck makes a handful of long stops a day, so this stays kilobytes
    regardless of how many million points were streamed to produce it.
    """

    distance_km: float = 0.0
    stops: list[_Stop] = field(default_factory=list)


class _TrackBuilder:
    """Incremental per-truck accumulator driven by the streaming scan."""

    def __init__(self) -> None:
        self.track = TruckTrack()
        self._prev_lat: float | None = None
        self._prev_lon: float | None = None
        # Open stop run, if the previous point was stopped.
        self._run_start: datetime | None = None
        self._run_lat = 0.0
        self._run_lon = 0.0
        self._run_last: datetime | None = None

    def add(self, recorded_at: datetime, lat: float, lon: float, speed: float) -> None:
        if self._prev_lat is not None:
            self.track.distance_km += _haversine_km(self._prev_lat, self._prev_lon, lat, lon)
        self._prev_lat, self._prev_lon = lat, lon

        if speed <= STOP_SPEED_KMH:
            if self._run_start is None:
                # Anchor the stop at its first point, matching how a dispatcher
                # reads it: "the truck stopped *here*, then sat for 40 minutes".
                self._run_start, self._run_lat, self._run_lon = recorded_at, lat, lon
            self._run_last = recorded_at
        else:
            self.close_run()

    def close_run(self) -> None:
        """End the open stop run and keep it if it lasted long enough."""
        if self._run_start is None or self._run_last is None:
            self._run_start = self._run_last = None
            return
        duration_min = (self._run_last - self._run_start).total_seconds() / 60.0
        if duration_min >= MIN_STOP_MINUTES:
            self.track.stops.append(
                _Stop(
                    started_at=self._run_start,
                    ended_at=self._run_last,
                    latitude=self._run_lat,
                    longitude=self._run_lon,
                    duration_minutes=duration_min,
                )
            )
        self._run_start = self._run_last = None


async def scan_tracks(
    db: AsyncSession, start: datetime, end: datetime, org_id
) -> dict[str, TruckTrack]:
    """Stream one org's GPS history and fold it into per-truck aggregates.

    Uses a server-side cursor (``AsyncSession.stream`` + ``yield_per``) and only
    the five columns the maths needs, so peak memory is ``SCAN_BATCH_ROWS``
    tuples plus one small :class:`TruckTrack` per truck — *not* one ORM object
    per GPS point. A 30-day window over a 20-truck fleet is ~1.4M rows; the
    previous implementation materialised all of them and would exhaust the
    worker long before the request finished.

    Ordering by ``(truck_id, recorded_at)`` matches the table's index, so
    Postgres streams this without a sort.
    """
    stmt = (
        select(
            TruckLocationHistory.truck_id,
            TruckLocationHistory.latitude,
            TruckLocationHistory.longitude,
            TruckLocationHistory.speed,
            TruckLocationHistory.recorded_at,
        )
        .join(Truck, Truck.id == TruckLocationHistory.truck_id)
        .where(
            TruckLocationHistory.recorded_at >= start,
            TruckLocationHistory.recorded_at <= end,
            Truck.org_id == org_id,
        )
        .order_by(TruckLocationHistory.truck_id, TruckLocationHistory.recorded_at)
        .execution_options(yield_per=SCAN_BATCH_ROWS)
    )

    builders: dict[str, _TrackBuilder] = {}
    current_tid: str | None = None
    current: _TrackBuilder | None = None

    result = await db.stream(stmt)
    async for truck_id, lat, lon, speed, recorded_at in result:
        tid = str(truck_id)
        if tid != current_tid:
            # Rows are grouped by truck, so a change of id ends the previous
            # truck's history — close whatever stop run it left open.
            if current is not None:
                current.close_run()
            current = builders.setdefault(tid, _TrackBuilder())
            current_tid = tid
        current.add(recorded_at, float(lat), float(lon), float(speed or 0))

    if current is not None:
        current.close_run()

    return {tid: b.track for tid, b in builders.items()}


def _point_in_any_fence(lat: float, lon: float, fences: list[tuple[float, float, float]]) -> bool:
    for flat, flon, radius_m in fences:
        if _haversine_km(lat, lon, flat, flon) * 1000.0 <= radius_m:
            return True
    return False


async def fuel_anomalies(
    db: AsyncSession, days: int, org_id, *, tracks: dict[str, TruckTrack] | None = None
) -> dict:
    """Per-truck fuel efficiency vs. fleet baseline; flags + estimated waste cost.

    ``tracks`` lets a caller that already scanned the window (see
    :func:`leakage_summary`) reuse it instead of paying for a second full scan.
    """
    days = effective_window_days(days)
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    if tracks is None:
        tracks = await scan_tracks(db, start, end, org_id)

    # Fuel litres + spend per truck in the window (this org only). Bounded to the
    # same window as the distance scan — see effective_window_days.
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
        "window_days": days,
        "baseline_l_per_100km": round(baseline, 1),
        "flagged_count": sum(1 for a in anomalies if a["flagged"]),
        "estimated_waste_cost": round(total_waste_cost, 2),
        "trucks": anomalies,
    }


async def unauthorized_stops(
    db: AsyncSession, days: int, org_id, *, tracks: dict[str, TruckTrack] | None = None
) -> dict:
    """Stops longer than MIN_STOP_MINUTES outside every active geofence."""
    days = effective_window_days(days)
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    if tracks is None:
        tracks = await scan_tracks(db, start, end, org_id)

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
        for stop in track.stops:
            # Idle time counts every long stop; only the ones outside a known
            # depot/customer become an actionable "unauthorized" row.
            total_idle_minutes += stop.duration_minutes
            if _point_in_any_fence(stop.latitude, stop.longitude, fences):
                continue
            t = trucks.get(tid)
            stops.append(
                {
                    "truck_id": tid,
                    "truck_name": t.name if t else "—",
                    "plate_number": t.plate_number if t else "—",
                    "latitude": round(stop.latitude, 5),
                    "longitude": round(stop.longitude, 5),
                    "started_at": stop.started_at,
                    "ended_at": stop.ended_at,
                    "duration_minutes": round(stop.duration_minutes, 1),
                }
            )

    stops.sort(key=lambda x: x["duration_minutes"], reverse=True)
    return {
        "window_days": days,
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

    Reads only fuel logs (never GPS history), so it is not clamped to the GPS
    retention window: the full requested period is genuinely available here.
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
    """Top-line money view: what leaked, and the trip-level health behind it.

    Scans the GPS window **once** and feeds both sub-reports from it; they used
    to run a full scan each, doubling the cost of the dashboard's headline call.
    """
    days = effective_window_days(days)
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)

    tracks = await scan_tracks(db, start, end, org_id)
    fuel = await fuel_anomalies(db, days, org_id, tracks=tracks)
    stops = await unauthorized_stops(db, days, org_id, tracks=tracks)

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
