"""Seed a full Uzbek demo tenant — for live product presentations.

Creates its own organization ("Silk Road Logistics") and fills it with 30 days
of believable operating history: 12 trucks on the real Toshkent–Samarqand–
Buxoro–Nukus corridors plus Qozog'iston/Rossiya international runs, GPS tracks,
UZS fuel logs, maintenance, freight trips with revenue, and driver-filled trip
expense reports ("yo'l varaqasi").

The generated data is deliberately shaped so the money-first screens have a
story to tell:

* two trucks burn ~45 L/100 km against a ~31 L/100 km fleet baseline, so the
  Leakage page shows flagged trucks and an estimated waste cost;
* several long stops sit outside every geofence (unauthorized-stop signal);
* three fuel fill-ups trip the fraud heuristics (oversized fill, inflated
  price, impossible consumption);
* a handful of trips are still in flight (en route / at the border) so the live
  map and the trips board are not all-green, each one scheduled around *now* so
  the board shows one genuinely late trip rather than a fleet weeks overdue;
* every truck on a running trip sits on that trip's own route, at a speed its
  status allows — see ``align_live_positions``;
* yesterday is a real working day — deliveries, distance, fuel and driver
  spending — because that single day is all the owner's morning digest reads.
  See ``seed_yesterday``.

**Scope**: every write is confined to this one organization. Other tenants —
including the real "Default Fleet" data on production — are never read or
touched, and ``--reset`` only deletes rows belonging to the demo org.

Run (DEMO_PASSWORD is required — see ``demo_data_uz.py``):
    DEMO_PASSWORD='...' python seed_demo_uz.py --reset    # wipe the demo org's rows first, then seed

``--reset`` is not optional in practice: without it the first truck re-inserted
collides with the plate already in the table. The two companion seeders —
``seed_demo_driver.py`` (mobile login) and ``seed_demo_telegram.py`` (owner and
cargo-owner chats) — run after this one; ``scripts/demo-setup.sh`` does all
three in order.
"""
from __future__ import annotations

import argparse
import asyncio
import math
import os
import random
import sys
import uuid
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import delete, select

import demo_data_uz as D
from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models.driver_app import DriverExpense, Shift
from app.models.drivers import Driver, DriverAssignment, SafetyScore
from app.models.enums import (
    DriverStatus,
    ExpenseCategory,
    ServiceStatus,
    ServiceType,
    ShiftStatus,
    TripEventType,
    TripReportCountry,
    TripReportExpenseCategory,
    TripReportStatus,
    TripStatus,
    TruckStatus,
    UserRole,
)
from app.models.geofences import Geofence
from app.models.maintenance import FuelLog, MaintenanceRecord, ServiceInterval
from app.models.notifications import TripSubscription
from app.models.organizations import Organization
from app.models.owner_alerts import NotificationLog
from app.models.trip_reports import TripCountryExpenseLine, TripExpenseReport, TripFuelRow
from app.models.trips import Trip, TripEvent
from app.models.trucks import Truck, TruckLocation, TruckLocationHistory
from app.models.users import User
from app.services.analytics import scan_tracks
# Private on purpose, and imported anyway: ``seed_yesterday`` has to measure
# the *same* window the digest reads, and a local re-derivation of "yesterday
# in Asia/Tashkent, as UTC" is exactly the thing that drifts out of step and
# leaves the digest reporting zero again.
from app.services.owner_alerts.briefing import _day_bounds_utc
from app.services.owner_alerts.leakage import WINDOW_DAYS as LEAKAGE_WINDOW_DAYS
from app.services.period_reports import report_tz

GPS_DAYS = 30           # how far back the location history reaches
TRIP_DAYS = 60          # how far back the trips board reaches
PING_MINUTES = 15       # spacing between GPS pings while moving
AVG_SPEED_KMH = 68.0    # planning speed used to size a journey

# Trucks (by index) that burn far more fuel than the fleet — the leakage story.
THIRSTY_TRUCKS = {3: 47.5, 9: 44.0}
NORMAL_CONSUMPTION = (29.0, 33.5)  # L/100 km

# Litres in each truck's planted fraud fill-up (see ``seed_fuel``). Kept here so
# the honest fills can be sized net of it.
PLANTED_LITERS = {3: 1_180.0, 6: 520.0, 9: 380.0}


# --------------------------------------------------------------------------- #
# Geometry helpers                                                             #
# --------------------------------------------------------------------------- #

def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    r = 6371.0
    lat1, lon1, lat2, lon2 = map(math.radians, [a[0], a[1], b[0], b[1]])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def lerp(a: tuple[float, float], b: tuple[float, float], t: float) -> tuple[float, float]:
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def jitter(p: tuple[float, float], scale: float = 0.01) -> tuple[float, float]:
    return (p[0] + random.uniform(-scale, scale), p[1] + random.uniform(-scale, scale))


def bearing(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lat2 = math.radians(a[0]), math.radians(b[0])
    dlon = math.radians(b[1] - a[1])
    y = math.sin(dlon) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return round((math.degrees(math.atan2(y, x)) + 360) % 360, 1)


def near_any_geofence(p: tuple[float, float], margin_km: float = 3.0) -> bool:
    """True if the point would be swallowed by an authorized zone.

    Used to place *unauthorized* stops somewhere the analytics service will
    actually flag them.
    """
    return any(
        haversine_km(p, (lat, lng)) <= (radius_m / 1000.0) + margin_km
        for _n, _c, lat, lng, radius_m in D.GEOFENCES
    )


def nearest_depot(p: tuple[float, float], max_km: float = 45.0) -> tuple[float, float] | None:
    """Closest depot/customer geofence centre, so a parked truck lands *inside* it.

    Rest stops at a city centre would otherwise be flagged as unauthorized —
    the geofences are at the real yard coordinates, not at the city pin.
    """
    candidates = [
        ((lat, lng), haversine_km(p, (lat, lng)))
        for _n, category, lat, lng, _r in D.GEOFENCES
        if category in ("depot", "customer")
    ]
    if not candidates:
        return None
    centre, distance = min(candidates, key=lambda c: c[1])
    return centre if distance <= max_km else None


# --------------------------------------------------------------------------- #
# Reset — strictly scoped to the demo organization                             #
# --------------------------------------------------------------------------- #

async def reset_org(db, org: Organization) -> None:
    """Delete every row belonging to this org. Never touches other tenants."""
    truck_ids = (await db.execute(select(Truck.id).where(Truck.org_id == org.id))).scalars().all()
    driver_ids = (await db.execute(select(Driver.id).where(Driver.org_id == org.id))).scalars().all()
    trip_ids = (await db.execute(select(Trip.id).where(Trip.org_id == org.id))).scalars().all()
    report_ids = (
        await db.execute(select(TripExpenseReport.id).where(TripExpenseReport.org_id == org.id))
    ).scalars().all()

    if report_ids:
        await db.execute(delete(TripCountryExpenseLine).where(TripCountryExpenseLine.report_id.in_(report_ids)))
        await db.execute(delete(TripFuelRow).where(TripFuelRow.report_id.in_(report_ids)))
    await db.execute(delete(TripExpenseReport).where(TripExpenseReport.org_id == org.id))

    if trip_ids:
        await db.execute(delete(TripEvent).where(TripEvent.trip_id.in_(trip_ids)))

    if driver_ids:
        await db.execute(delete(DriverExpense).where(DriverExpense.driver_id.in_(driver_ids)))
        await db.execute(delete(Shift).where(Shift.driver_id.in_(driver_ids)))
        await db.execute(delete(SafetyScore).where(SafetyScore.driver_id.in_(driver_ids)))
        await db.execute(delete(DriverAssignment).where(DriverAssignment.driver_id.in_(driver_ids)))

    if truck_ids:
        await db.execute(delete(TruckLocationHistory).where(TruckLocationHistory.truck_id.in_(truck_ids)))
        await db.execute(delete(TruckLocation).where(TruckLocation.truck_id.in_(truck_ids)))
        await db.execute(delete(FuelLog).where(FuelLog.truck_id.in_(truck_ids)))
        await db.execute(delete(MaintenanceRecord).where(MaintenanceRecord.truck_id.in_(truck_ids)))
        await db.execute(delete(ServiceInterval).where(ServiceInterval.truck_id.in_(truck_ids)))

    # Cargo-owner subscriptions die with their trip anyway (the FK cascades),
    # but saying so here keeps this function's promise true on a database whose
    # constraint was created without it.
    await db.execute(delete(TripSubscription).where(TripSubscription.org_id == org.id))

    # The alert dedupe log, on the other hand, is keyed on the *fact* and not
    # on any row, so nothing cascades it away. Left behind it silences the new
    # fleet: yesterday's "01 A 447 BC is overdue for service" is still the
    # newest word on that plate, and the watcher declines to repeat itself.
    #
    # ``TelegramAccount`` is deliberately NOT cleared. It holds the chat id an
    # owner produced by opening a magic link, and re-seeding the fleet is not a
    # reason to make them do that again — least of all ten minutes before a
    # presentation.
    await db.execute(delete(NotificationLog).where(NotificationLog.org_id == org.id))

    await db.execute(delete(Trip).where(Trip.org_id == org.id))
    await db.execute(delete(Geofence).where(Geofence.org_id == org.id))
    await db.execute(delete(Driver).where(Driver.org_id == org.id))
    await db.execute(delete(Truck).where(Truck.org_id == org.id))
    await db.commit()
    print(f"  reset: cleared {len(truck_ids)} trucks / {len(trip_ids)} trips from '{org.name}'")


# --------------------------------------------------------------------------- #
# Core entities                                                                #
# --------------------------------------------------------------------------- #

async def seed_org(db) -> Organization:
    org = (
        await db.execute(select(Organization).where(Organization.name == D.ORG_NAME))
    ).scalar_one_or_none()
    if org is None:
        org = Organization(
            id=uuid.uuid4(),
            name=D.ORG_NAME,
            contact_name=D.ORG_CONTACT_NAME,
            contact_phone=D.ORG_CONTACT_PHONE,
            notes=D.ORG_NOTES,
        )
        db.add(org)
        await db.commit()
        await db.refresh(org)
    print(f"  org: {org.name} ({org.id})")
    return org


async def seed_users(db, org: Organization, password: str) -> None:
    """Create the demo logins, or re-point the ones already there.

    Re-hashing rather than skipping, which is what this used to do. Skipping
    left the seeder telling the truth about everything except the one fact a
    presenter needs: after a re-seed the accounts still carried whatever
    password the *first* seed had used, so ``DEMO_PASSWORD`` set today opened
    nothing and the failure surfaced at the login screen in front of a customer.
    ``seed_demo_driver.py`` already re-points its account for the same reason.

    Safe because the set is closed: ``DEMO_USERS`` is two @silkroad.uz
    addresses in the demo org, never a real customer's login.
    """
    for email, role in D.DEMO_USERS:
        existing = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
        if existing:
            existing.org_id = org.id
            existing.role = UserRole(role)
            existing.password_hash = hash_password(password)
            continue
        db.add(User(
            org_id=org.id,
            email=email,
            password_hash=hash_password(password),
            role=UserRole(role),
        ))
    await db.commit()
    # The password is deliberately not echoed. This runs against production, and
    # a printed credential ends up in shell history, CI logs and screen shares.
    print(f"  users: {', '.join(e for e, _ in D.DEMO_USERS)}")


async def seed_geofences(db, org: Organization) -> None:
    for name, category, lat, lng, radius in D.GEOFENCES:
        db.add(Geofence(
            org_id=org.id, name=name, category=category,
            center_lat=lat, center_lng=lng, radius_m=radius, active=True,
        ))
    await db.commit()
    print(f"  geofences: {len(D.GEOFENCES)}")


async def seed_trucks(db, org: Organization) -> list[Truck]:
    statuses = (
        [TruckStatus.moving] * 6
        + [TruckStatus.stopped] * 3
        + [TruckStatus.idle] * 2
        + [TruckStatus.maintenance]
    )
    trucks: list[Truck] = []
    for i, (name, plate, model, year, mileage) in enumerate(D.TRUCKS):
        truck = Truck(
            id=uuid.uuid4(),
            org_id=org.id,
            name=name,
            plate_number=plate,
            model=model,
            year=year,
            status=statuses[i],
            fuel_level=round(random.uniform(28, 96), 1),
            mileage=float(mileage),
        )
        db.add(truck)
        trucks.append(truck)
    await db.commit()
    print(f"  trucks: {len(trucks)}")
    return trucks


async def seed_drivers(db, org: Organization, trucks: list[Truck]) -> list[Driver]:
    today = date.today()
    drivers: list[Driver] = []
    for name, phone, license_no, email in D.DRIVERS:
        driver = Driver(
            id=uuid.uuid4(),
            org_id=org.id,
            name=name,
            phone=phone,
            email=email,
            license_number=license_no,
            license_expiry=today + timedelta(days=random.randint(45, 1_100)),
            status=DriverStatus.active,
        )
        db.add(driver)
        drivers.append(driver)
    await db.commit()

    now = datetime.now(timezone.utc)
    for driver, truck in zip(drivers, trucks):
        db.add(DriverAssignment(
            driver_id=driver.id,
            truck_id=truck.id,
            assigned_at=now - timedelta(days=random.randint(60, 500)),
        ))
        db.add(SafetyScore(
            driver_id=driver.id,
            score=random.randint(68, 97),
            speeding_events=random.randint(0, 14),
            harsh_braking=random.randint(0, 11),
            harsh_acceleration=random.randint(0, 9),
            idle_time_minutes=random.randint(120, 1_400),
            period_start=today - timedelta(days=30),
            period_end=today,
        ))
    await db.commit()
    print(f"  drivers: {len(drivers)} (barchasi mashinaga biriktirilgan) + safety scores")
    return drivers


# --------------------------------------------------------------------------- #
# GPS history                                                                  #
# --------------------------------------------------------------------------- #

def _stop_points(at: tuple[float, float], start: datetime, minutes: int) -> list[tuple]:
    """A run of near-zero-speed pings — what a parked truck looks like on GPS."""
    points = []
    elapsed = 0
    while elapsed <= minutes:
        points.append((start + timedelta(minutes=elapsed), jitter(at, 0.0004), round(random.uniform(0, 2.5), 1)))
        elapsed += PING_MINUTES
    return points


def build_journey(origin: tuple[float, float], dest: tuple[float, float], start: datetime,
                  depot_stop: bool, long_stops: int) -> list[tuple]:
    """One origin→destination run as (timestamp, (lat, lng), speed) tuples.

    Both ends are generated above the stopped-speed threshold on purpose: the
    analytics service groups *consecutive* slow pings into one stop, so a slow
    first/last ping would merge two journeys into a multi-day phantom stop.
    """
    straight_km = haversine_km(origin, dest)
    steps = max(20, int(straight_km / AVG_SPEED_KMH * (60 / PING_MINUTES)))
    steps = min(steps, 160)  # keep Moskva runs from dominating the table

    points: list[tuple] = []
    clock = start

    depot = nearest_depot(origin) if depot_stop else None
    if depot:
        points.append((clock, jitter(depot, 0.002), round(random.uniform(18, 30), 1)))
        clock += timedelta(minutes=PING_MINUTES)
        stop = _stop_points(depot, clock, random.randint(45, 90))
        points.extend(stop)
        clock = stop[-1][0] + timedelta(minutes=PING_MINUTES)

    stop_at_steps = sorted(random.sample(range(2, max(3, steps - 2)), k=min(long_stops, max(1, steps - 4))))

    for i in range(steps):
        t = i / (steps - 1)
        pos = jitter(lerp(origin, dest, t), 0.012)
        speed = round(random.uniform(62, 92), 1)
        if i == 0:
            speed = round(random.uniform(20, 35), 1)
        elif i == steps - 1:
            speed = round(random.uniform(14, 26), 1)
        points.append((clock, pos, speed))
        clock += timedelta(minutes=PING_MINUTES)

        if i in stop_at_steps and not near_any_geofence(pos):
            stop = _stop_points(pos, clock, random.randint(40, 140))
            points.extend(stop)
            clock = stop[-1][0] + timedelta(minutes=PING_MINUTES)

    return points


async def seed_gps(db, trucks: list[Truck]) -> dict[str, float]:
    """Write GPS history + a live position per truck; return km driven per truck."""
    now = datetime.now(timezone.utc)
    km_by_truck: dict[str, float] = {}
    total_pings = 0

    for idx, truck in enumerate(trucks):
        thirsty = idx in THIRSTY_TRUCKS
        journeys = random.randint(4, 6)
        driven = 0.0
        last_point: tuple | None = None
        # Each journey starts where the previous one ended. Without this the
        # truck teleports between legs and the analytics distance — which just
        # sums haversine over consecutive pings — comes out several times too
        # high, dragging the L/100 km baseline down to nonsense.
        current_city = "Toshkent"

        for j in range(journeys):
            legs = [c for c in D.CORRIDORS if current_city in (c[0], c[1])]
            origin_name, dest_name, _km, _rate, _intl = random.choice(legs or D.CORRIDORS)
            if dest_name == current_city:
                origin_name, dest_name = dest_name, origin_name
            origin, dest = D.CITIES[origin_name], D.CITIES[dest_name]

            day_offset = GPS_DAYS - int(j * (GPS_DAYS / journeys)) - 1
            start = now - timedelta(days=day_offset, hours=random.randint(2, 10))

            # Thirsty trucks idle far more often — that is the leak we surface.
            long_stops = 2 if thirsty else (1 if random.random() < 0.3 else 0)
            points = build_journey(origin, dest, start, depot_stop=(j == 0), long_stops=long_stops)

            prev_pos = None
            for ts, pos, speed in points:
                if prev_pos is not None:
                    driven += haversine_km(prev_pos, pos)
                prev_pos = pos
                db.add(TruckLocationHistory(
                    truck_id=truck.id,
                    latitude=pos[0], longitude=pos[1],
                    speed=speed,
                    heading=bearing(origin, dest),
                    recorded_at=ts,
                ))
                total_pings += 1
            last_point = (points[-1][1], bearing(origin, dest), dest_name)
            current_city = dest_name

        km_by_truck[str(truck.id)] = driven

        pos, heading, near = last_point if last_point else (D.CITIES["Toshkent"], 0.0, "Toshkent")
        db.add(TruckLocation(
            truck_id=truck.id,
            latitude=pos[0], longitude=pos[1],
            speed=round(random.uniform(58, 88), 1) if truck.status == TruckStatus.moving else 0.0,
            heading=heading,
            address=f"{near} yo'nalishi",
            recorded_at=now - timedelta(minutes=random.randint(1, 9)),
        ))

    await db.commit()
    print(f"  gps: {total_pings} ping, {len(trucks)} jonli pozitsiya")
    return km_by_truck


# --------------------------------------------------------------------------- #
# Fuel — including the three fraud signatures                                  #
# --------------------------------------------------------------------------- #

async def seed_fuel(db, trucks: list[Truck], km_by_truck: dict[str, float]) -> None:
    now = datetime.now(timezone.utc)
    total = 0

    for idx, truck in enumerate(trucks):
        distance = km_by_truck.get(str(truck.id), 0.0)
        if distance < 50:
            continue
        target = THIRSTY_TRUCKS.get(idx) or random.uniform(*NORMAL_CONSUMPTION)
        # The planted fraud row is part of the truck's consumption, not on top of
        # it — otherwise a small fleet's flagged trucks end up at an absurd
        # ~100 L/100 km and the demo stops being believable.
        total_liters = max(distance * target / 100.0 - PLANTED_LITERS.get(idx, 0.0), 150.0)
        fills = max(2, round(total_liters / 600))
        per_fill = total_liters / fills

        odometer = float(truck.mileage) - distance
        rows: list[dict] = []
        for f in range(fills):
            # Spread across days 28→8, stopping clear of the last week.
            # ``seed_yesterday`` owns days 7→0 and sizes its fills from the
            # distance actually driven there; a fill from this pass landing
            # inside that window adds litres sized against thirty days of
            # driving to seven days of distance, which is what pushed the
            # leakage alert's fleet baseline to an impossible 65 L/100 km.
            filled_at = now - timedelta(
                days=28 - f * (20 / max(fills - 1, 1)), hours=random.randint(0, 20)
            )
            odometer += distance / fills
            rows.append({
                "liters": round(per_fill * random.uniform(0.9, 1.1), 1),
                "price": float(random.randint(*D.DIESEL_PRICE_UZS)),
                "odometer": round(odometer, 0),
                "filled_at": filled_at,
                "station": random.choice(D.FUEL_STATIONS_UZ + D.FUEL_STATIONS_FOREIGN),
            })

        # --- planted fraud signals, one per affected truck ------------------ #
        # Always appended as the truck's most recent fill: the heuristics compare
        # each row against the previous one, so a planted row inserted mid-history
        # would also mis-flag the (innocent) row that follows it.
        rows.sort(key=lambda r: r["filled_at"])
        planted: dict | None = None
        if idx == 3:  # oversized fill — more litres than any tank holds
            planted = {
                "liters": PLANTED_LITERS[3],
                "price": float(random.randint(*D.DIESEL_PRICE_UZS)),
                "odometer": rows[-1]["odometer"] + 640,
                "station": "Sardor Oil — Jizzax",
            }
        elif idx == 6:  # inflated receipt — price well above this truck's median
            planted = {
                "liters": PLANTED_LITERS[6],
                "price": round(sum(r["price"] for r in rows) / len(rows) * 1.62, 2),
                "odometer": rows[-1]["odometer"] + 1_450,
                "station": "Noma'lum AYoQSh — Guliston yo'li",
            }
        elif idx == 9:  # bought a full tank while the odometer barely moved
            planted = {
                "liters": PLANTED_LITERS[9],
                "price": float(random.randint(*D.DIESEL_PRICE_UZS)),
                "odometer": rows[-1]["odometer"] + 3,
                "station": "Neftgaz Servis — Guliston",
            }
        if planted:
            planted["filled_at"] = now - timedelta(days=random.uniform(1.0, 2.5))
            rows.append(planted)
        for r in rows:
            db.add(FuelLog(
                truck_id=truck.id,
                liters=r["liters"],
                cost_per_liter=r["price"],
                total_cost=round(r["liters"] * r["price"], 2),
                mileage_at_fill=r["odometer"],
                fuel_station=r["station"],
                filled_at=r["filled_at"],
            ))
            total += 1

    await db.commit()
    print(f"  fuel logs: {total} (3 ta firibgarlik signali ekilgan)")


# --------------------------------------------------------------------------- #
# Maintenance                                                                  #
# --------------------------------------------------------------------------- #

MAINT_COST_UZS = {
    ServiceType.oil_change: (1_800_000, 3_400_000),
    ServiceType.tire_rotation: (600_000, 1_500_000),
    ServiceType.brake_inspection: (2_400_000, 7_800_000),
    ServiceType.engine_service: (9_000_000, 28_000_000),
    ServiceType.transmission: (12_000_000, 42_000_000),
    ServiceType.general: (900_000, 5_200_000),
}


async def link_fuel_to_trips(db, org: Organization) -> None:
    """Attach each fuel fill to the trip that truck was running at the time.

    Fuel has to be seeded before trips — the trips are built from the same GPS
    tracks the fills are spaced along — so it cannot be linked at creation.
    This second pass does what the driver app now does at the point of sale:
    match the fill to the load that was open.

    Without it the demo reproduces the exact bug this release fixes. Every trip
    would show zero fuel cost and a margin near 100%, which on freight is not a
    number anyone would believe twice.
    """
    fills = (
        await db.execute(
            select(FuelLog)
            .join(Truck, Truck.id == FuelLog.truck_id)
            .where(Truck.org_id == org.id)
        )
    ).scalars().all()
    trips = (
        await db.execute(select(Trip).where(Trip.org_id == org.id))
    ).scalars().all()

    by_truck: dict[uuid.UUID, list[Trip]] = {}
    for trip in trips:
        if trip.truck_id and trip.started_at:
            by_truck.setdefault(trip.truck_id, []).append(trip)

    linked = 0
    for fill in fills:
        for trip in by_truck.get(fill.truck_id, ()):
            # A trip still on the road has no delivered_at; it owns everything
            # from its start onwards.
            end = trip.delivered_at
            if trip.started_at <= fill.filled_at and (end is None or fill.filled_at <= end):
                fill.trip_id = trip.id
                linked += 1
                break

    await db.commit()
    print(f"  fuel → trip: {linked}/{len(fills)} ta quyish reysga bog'landi")


async def seed_maintenance(db, trucks: list[Truck]) -> None:
    today = date.today()
    intervals = records = 0

    for truck in trucks:
        mileage = float(truck.mileage)
        spec = [
            (ServiceType.oil_change, 20_000, 180, random.randint(6_000, 22_000), random.randint(40, 210)),
            (ServiceType.tire_rotation, 50_000, 365, random.randint(12_000, 46_000), random.randint(80, 300)),
            (ServiceType.brake_inspection, 80_000, 730, random.randint(20_000, 70_000), random.randint(120, 500)),
        ]
        for service_type, interval_km, interval_days, since_km, since_days in spec:
            last_km = mileage - since_km
            last_date = today - timedelta(days=since_days)
            next_km = last_km + interval_km
            next_date = last_date + timedelta(days=interval_days)
            status = ServiceStatus.overdue if (today >= next_date or mileage >= next_km) else ServiceStatus.scheduled
            db.add(ServiceInterval(
                truck_id=truck.id,
                service_type=service_type,
                interval_km=interval_km,
                interval_days=interval_days,
                last_service_date=last_date,
                last_service_mileage=last_km,
                next_service_date=next_date,
                next_service_mileage=next_km,
                status=status,
            ))
            intervals += 1

        for _ in range(random.randint(4, 7)):
            # Weighted, not uniform: routine oil/tyre work dominates a real
            # workshop log, and drawing engine/transmission rebuilds 1-in-6 of
            # the time would put the yearly maintenance bill above revenue.
            service_type = random.choices(
                list(ServiceType),
                weights=[34, 24, 18, 8, 4, 12],  # oil, tyres, brakes, engine, transmission, general
            )[0]
            low, high = MAINT_COST_UZS[service_type]
            db.add(MaintenanceRecord(
                truck_id=truck.id,
                service_type=service_type,
                description=f"{service_type.value.replace('_', ' ').title()} — rejali xizmat",
                cost=round(random.uniform(low, high), 2),
                mileage_at_service=mileage - random.uniform(1_000, 60_000),
                performed_by=random.choice(D.SERVICE_VENDORS),
                performed_at=today - timedelta(days=random.randint(5, 340)),
                notes=random.choice(D.MAINT_NOTES),
            ))
            records += 1

    await db.commit()
    print(f"  maintenance: {intervals} interval, {records} yozuv")


# --------------------------------------------------------------------------- #
# Trips — the revenue layer                                                    #
# --------------------------------------------------------------------------- #

ACTIVE_TAIL = [
    TripStatus.en_route,
    TripStatus.en_route,
    TripStatus.en_route,
    TripStatus.at_border,
    TripStatus.loading,
    TripStatus.planned,
]

# How far into its own planned duration each running trip is, right now. One
# entry per ``ACTIVE_TAIL`` slot.
#
# Spread on purpose: identical progress puts every marker at the same point of
# its route and — because ``live_pose`` derives speed from progress — gives the
# whole fleet one speed. The 1.18 is the deliberate exception: that trip is
# 18% past its promised arrival and still moving, which is what gives the
# trips board one genuinely late row and the owner-alert delay watcher one
# true thing to report. A negative value means the trip has not started yet.
TAIL_PROGRESS = [0.34, 0.61, 1.18, 0.55, 0.05, -0.12]


async def seed_trips(db, org: Organization, trucks: list[Truck], drivers: list[Driver]) -> list[Trip]:
    now = datetime.now(timezone.utc)
    trips: list[Trip] = []
    counter = 1

    for idx, truck in enumerate(trucks):
        driver = drivers[idx] if idx < len(drivers) else random.choice(drivers)
        for j in range(random.randint(6, 9)):
            # The last trip of the first six trucks is still running — so the
            # live map and the trips board are not uniformly "delivered".
            is_tail = (j == 2) and idx < len(ACTIVE_TAIL)
            status = ACTIVE_TAIL[idx] if is_tail else TripStatus.delivered

            # Route is picked after the status, not before, because one status
            # constrains it: a truck cannot be "at the border" on the Toshkent–
            # Buxoro run. Left unconstrained the board shows a domestic trip
            # waiting at customs, which is the first thing a fleet owner in the
            # room notices and the last thing they forget.
            pool = [c for c in D.CORRIDORS if c[4]] if status == TripStatus.at_border else D.CORRIDORS
            origin_name, dest_name, distance_km, rate, international = random.choice(pool)
            origin, dest = D.CITIES[origin_name], D.CITIES[dest_name]
            cargo, weight, reefer = random.choice(D.CARGO)

            duration_h = distance_km / 55.0 + (18 if international else 4)

            if is_tail:
                # A running trip is scheduled backwards from *now*, not from a
                # random day in the past. Drawn from the same 2–60 day pool as
                # the delivered ones, these came out forty days into a twelve
                # hour run and still "en route" — every one of them weeks
                # overdue on the board, and all of them pinned to the same
                # clamp in ``live_pose`` so the fleet page showed three trucks
                # at an identical 87.8 km/h.
                scheduled_start = now - timedelta(hours=duration_h * TAIL_PROGRESS[idx])
            else:
                days_ago = random.randint(2, TRIP_DAYS)
                scheduled_start = now - timedelta(days=days_ago, hours=random.randint(0, 12))
            scheduled_end = scheduled_start + timedelta(hours=duration_h)

            started_at = None if status == TripStatus.planned else scheduled_start + timedelta(hours=random.uniform(0, 3))
            delivered_at = None
            if status == TripStatus.delivered:
                delivered_at = scheduled_end + timedelta(hours=random.uniform(-4, 26))

            trip = Trip(
                id=uuid.uuid4(),
                org_id=org.id,
                reference=f"TR-2026-{counter:04d}",
                truck_id=truck.id,
                driver_id=driver.id,
                status=status,
                shipper=random.choice(D.SHIPPERS),
                consignee=random.choice(D.CONSIGNEES),
                origin_name=origin_name,
                origin_lat=origin[0], origin_lng=origin[1],
                destination_name=dest_name,
                destination_lat=dest[0], destination_lng=dest[1],
                cargo_description=cargo,
                cargo_weight_kg=weight * random.uniform(0.8, 1.05),
                is_reefer=reefer,
                rate=round(rate * random.uniform(0.92, 1.14), 2),
                currency="UZS",
                planned_distance_km=distance_km,
                scheduled_start=scheduled_start,
                scheduled_end=scheduled_end,
                started_at=started_at,
                delivered_at=delivered_at,
                notes="Xalqaro reys — CMR va bojxona hujjatlari talab qilinadi." if international else None,
                created_at=scheduled_start - timedelta(days=random.randint(1, 4)),
            )
            db.add(trip)
            trips.append(trip)
            counter += 1

            _add_trip_events(db, trip, international)

    await db.commit()
    delivered = sum(1 for t in trips if t.status == TripStatus.delivered)
    print(f"  trips: {len(trips)} ({delivered} yetkazilgan, {len(trips) - delivered} jarayonda)")
    return trips


def _add_trip_events(db, trip: Trip, international: bool) -> None:
    clock = trip.created_at
    db.add(TripEvent(trip_id=trip.id, event=TripEventType.created,
                     to_status=TripStatus.draft, note="Reys yaratildi", recorded_at=clock))

    timeline: list[tuple[TripStatus, TripStatus]] = [(TripStatus.draft, TripStatus.planned)]
    if trip.status != TripStatus.planned:
        timeline.append((TripStatus.planned, TripStatus.loading))
    if trip.status in (TripStatus.en_route, TripStatus.at_border, TripStatus.delivered):
        timeline.append((TripStatus.loading, TripStatus.en_route))
    if trip.status in (TripStatus.at_border, TripStatus.delivered) and international:
        timeline.append((TripStatus.en_route, TripStatus.at_border))
    if trip.status == TripStatus.delivered:
        timeline.append((timeline[-1][1], TripStatus.delivered))

    for from_status, to_status in timeline:
        clock += timedelta(hours=random.uniform(2, 14))
        db.add(TripEvent(trip_id=trip.id, event=TripEventType.status_change,
                         from_status=from_status, to_status=to_status, recorded_at=clock))

    if international and trip.status in (TripStatus.at_border, TripStatus.delivered):
        post, coords = random.choice(list(D.BORDER_POSTS.items()))
        arrival = clock - timedelta(hours=random.uniform(6, 30))
        db.add(TripEvent(trip_id=trip.id, event=TripEventType.border_arrival,
                         note=f"{post} — navbatga turildi",
                         latitude=coords[0], longitude=coords[1], recorded_at=arrival))
        if trip.status == TripStatus.delivered:
            db.add(TripEvent(trip_id=trip.id, event=TripEventType.border_clear,
                             note=f"{post} — rasmiylashtirish yakunlandi",
                             latitude=coords[0], longitude=coords[1],
                             recorded_at=arrival + timedelta(hours=random.uniform(3, 22))))

    if trip.status == TripStatus.delivered and trip.delivered_at:
        db.add(TripEvent(trip_id=trip.id, event=TripEventType.pod,
                         note="Yuk qabul qilindi, CMR imzolandi",
                         latitude=float(trip.destination_lat), longitude=float(trip.destination_lng),
                         recorded_at=trip.delivered_at))


# --------------------------------------------------------------------------- #
# Live pose — put each truck where its running trip says it is                  #
# --------------------------------------------------------------------------- #
#
# ``seed_gps`` walks every truck through corridors chosen at random, and
# ``seed_trips`` picks each trip's route independently. Both are fine on their
# own and contradict each other the moment they meet on screen: a trip whose
# status reads "chegarada" while its truck's marker sits in Yekaterinburg, or
# one "yuklanmoqda" at 66 km/h in another country. The dispatcher board, the
# live map and the cargo owner's Telegram message all read from that one
# position, so the contradiction shows up three times in the first two minutes
# of a demo.
#
# This runs last and reconciles them in the only direction that can't lose
# information: the trip is the story, so the truck is moved to the trip.
# History is deliberately left alone — the thirty days behind it are what the
# fuel baseline and the leakage figures are computed from.

# status → (truck status, speed range). A truck waiting to be loaded, or
# sitting in a customs queue, is not doing 70 km/h.
LIVE_POSE: dict[TripStatus, tuple[TruckStatus, tuple[float, float]]] = {
    TripStatus.planned: (TruckStatus.idle, (0.0, 0.0)),
    TripStatus.loading: (TruckStatus.stopped, (0.0, 0.0)),
    TripStatus.en_route: (TruckStatus.moving, (58.0, 88.0)),
    TripStatus.at_border: (TruckStatus.stopped, (0.0, 0.0)),
}


def crossing_for(origin: tuple[float, float], dest: tuple[float, float]) -> tuple[str, tuple[float, float]]:
    """The border post that least detours the route.

    Nearest-to-origin would put a Dushanbe run through a Qozog'iston post;
    minimising the total detour picks Oybek for that one and Gishtko'prik for
    Shymkent, which is what the paperwork would say.
    """
    return min(
        D.BORDER_POSTS.items(),
        key=lambda item: haversine_km(origin, item[1]) + haversine_km(item[1], dest),
    )


def live_pose(trip: Trip, now: datetime) -> tuple[tuple[float, float], float, str]:
    """Where a truck on this trip is right now: (position, speed, address)."""
    origin = (float(trip.origin_lat), float(trip.origin_lng))
    dest = (float(trip.destination_lat), float(trip.destination_lng))

    if trip.status == TripStatus.at_border:
        name, coords = crossing_for(origin, dest)
        return jitter(coords, 0.004), 0.0, f"{name} — navbatda"

    if trip.status in (TripStatus.planned, TripStatus.loading):
        label = "yuklanmoqda" if trip.status == TripStatus.loading else "jo'nashga tayyor"
        return jitter(origin, 0.008), 0.0, f"{trip.origin_name} — {label}"

    # En route: how far along the planned schedule the clock actually is.
    # Clamped away from both ends so the marker reads as "on the road" rather
    # than as a truck that has arrived but not been marked delivered.
    planned = (trip.scheduled_end - trip.scheduled_start).total_seconds()
    elapsed = (now - (trip.started_at or trip.scheduled_start)).total_seconds()
    progress = min(0.82, max(0.18, elapsed / planned if planned > 0 else 0.5))

    # Speed is derived from where the truck is, not drawn beside it. Three
    # trucks sampled one after another out of the same fixed-seed generator
    # came out at 86.7, 86.7 and 86.4 km/h — and a fixed seed means that
    # coincidence is permanent, so the fleet page would show the same
    # templated-looking column at every demo. Tying it to progress also earns
    # its keep: a truck near either end of its run is slowing down.
    _status, (low, high) = LIVE_POSE[trip.status]
    ramp = min(1.0, 1.4 * min(progress, 1.0 - progress) + 0.35)
    speed = round((low + (high - low) * ramp) * random.uniform(0.9, 1.04), 1)
    return (
        jitter(lerp(origin, dest, progress), 0.01),
        min(high, speed),
        f"{trip.origin_name} → {trip.destination_name} yo'nalishi",
    )


async def align_live_positions(db, trips: list[Trip]) -> int:
    """Move every truck with a running trip onto that trip's route."""
    now = datetime.now(timezone.utc)
    running = [t for t in trips if t.status in LIVE_POSE and t.truck_id is not None]

    for trip in running:
        truck = (await db.execute(select(Truck).where(Truck.id == trip.truck_id))).scalar_one()
        # A truck the seed parked in the workshop cannot also be out on a run.
        # Let the trip win and say so, rather than leaving the fleet page
        # claiming a maintenance truck is en route to Moskva.
        truck.status = LIVE_POSE[trip.status][0]

        pos, speed, address = live_pose(trip, now)
        location = (
            await db.execute(select(TruckLocation).where(TruckLocation.truck_id == truck.id))
        ).scalar_one_or_none()
        heading = bearing(
            (float(trip.origin_lat), float(trip.origin_lng)),
            (float(trip.destination_lat), float(trip.destination_lng)),
        )
        recorded = now - timedelta(minutes=random.randint(1, 6))
        if location is None:
            db.add(TruckLocation(
                truck_id=truck.id, latitude=pos[0], longitude=pos[1],
                speed=speed, heading=heading, address=address, recorded_at=recorded,
            ))
        else:
            location.latitude, location.longitude = pos[0], pos[1]
            location.speed = speed
            location.heading = heading
            location.address = address
            location.recorded_at = recorded

    await db.commit()
    print(f"  jonli pozitsiya: {len(running)} ta mashina o'z reysi yo'nalishiga joylandi")
    return len(running)


# --------------------------------------------------------------------------- #
# Yesterday — the one day the owner's morning digest actually reports on        #
# --------------------------------------------------------------------------- #
#
# Every generator above spreads its rows across a window that stops short of
# the present: GPS journeys land 30→5 days back, fuel fills 28→4, delivered
# trips anywhere in 60 days. Each is reasonable alone, and together they leave
# *yesterday* empty — which is the single day ``owner_alerts.briefing`` reads.
# The digest that is supposed to close a presentation came out as five zeroes:
# "kecha 0 ta yetkazildi, 0 km, 0 l, 0 so'm".
#
# Rather than widen four windows and re-tune the leakage figures they feed,
# this runs last and gives yesterday one believable working day.
#
# Two invariants it is written around:
#
# * **No teleports.** Each added journey starts at that truck's most recent
#   history point. ``scan_tracks`` measures distance by summing haversine over
#   consecutive pings, so a journey starting anywhere else would bill the fleet
#   for a jump across the map and inflate the 30-day distance the fuel baseline
#   divides by.
# * **Consumption is preserved.** Every added kilometre comes with the litres
#   that truck already burns per kilometre, so L/100 km — and therefore which
#   trucks the Leakage page flags — is exactly what it was before.

RECENT_DAYS = 6             # how far back the "recent week" pass reaches
RECENT_JOURNEYS = 3         # journeys per truck inside that week
YESTERDAY_DELIVERIES = 3    # delivered trips re-timed into yesterday
YESTERDAY_START_HOUR = 6    # local hour the working day begins


def _yesterday_local() -> tuple[date, datetime]:
    """Yesterday's local date, and 06:00 local on it as an aware datetime."""
    tz = report_tz()
    day = datetime.now(tz).date() - timedelta(days=1)
    return day, datetime.combine(day, time(YESTERDAY_START_HOUR, 0), tzinfo=tz)


def _reachable_city(origin: tuple[float, float]) -> tuple[str, tuple[float, float]]:
    """A city near enough to drive to between breakfast and bedtime.

    Bounded above so the journey fits inside the day it is meant to fill: a
    Moskva leg would run its pings past midnight and into a day the digest
    does not look at.
    """
    candidates = [
        (name, coords)
        for name, coords in D.CITIES.items()
        if 150.0 <= haversine_km(origin, coords) <= 620.0
    ]
    return random.choice(candidates) if candidates else ("Toshkent", D.CITIES["Toshkent"])


async def seed_yesterday(db, org: Organization, trucks: list[Truck], trips: list[Trip]) -> None:
    day, start = _yesterday_local()
    rates: dict[str, float] = {}

    # ── Every truck works the week, not just yesterday ────────────────────
    #
    # The owner's leakage alert divides litres by kilometres over a rolling
    # **7-day** window (``leakage.WINDOW_DAYS``), while seed_gps stops five days
    # back and seed_fuel four. Inside that window the fleet had bought fuel and
    # barely moved, so the alert announced a truck at 265.7 L/100 km against a
    # fleet baseline of 74.0 — both impossible, in the one message the demo
    # leads with. Filling the week for every truck puts the baseline back at a
    # real ~31 L/100 km, which is what makes the thirsty ones stand out instead
    # of drowning in noise.
    for idx, truck in enumerate(trucks):
        last = (
            await db.execute(
                select(TruckLocationHistory)
                .where(TruckLocationHistory.truck_id == truck.id)
                .order_by(TruckLocationHistory.recorded_at.desc())
                .limit(1)
            )
        ).scalars().first()
        if last is None:
            continue

        here = (float(last.latitude), float(last.longitude))

        # The chain has to begin *after* the truck's newest existing ping, not
        # at a fixed six days back. seed_gps leaves off around five days ago, so
        # a fixed start interleaved the new legs with the old tail: ordered by
        # time the track then jumped between two cities and back on every ping,
        # and the week's distance came out near 100 000 km — enough to overflow
        # the litres column that is sized from it.
        floor = last.recorded_at + timedelta(hours=2)
        window_start = max(floor, start - timedelta(days=RECENT_DAYS))
        span_h = (start + timedelta(hours=12) - window_start).total_seconds() / 3600.0
        if span_h < 12:
            continue
        legs = max(1, min(RECENT_JOURNEYS, int(span_h // 14)))

        for leg in range(legs):
            # Evenly spaced, with the **last** leg pinned to yesterday morning.
            # The week needs distance everywhere for the leakage ratio, but the
            # morning digest reads one day only — spread the legs freely and
            # yesterday comes out empty, which is how the digest went back to
            # reporting 124 km and no fuel at all.
            leg_start = (
                start if leg == legs - 1
                else window_start + timedelta(
                    hours=(start - window_start).total_seconds() / 3600.0 * leg / max(legs - 1, 1)
                )
            )
            dest_name, dest = _reachable_city(here)
            points = build_journey(here, dest, leg_start, depot_stop=False,
                                   long_stops=1 if idx in THIRSTY_TRUCKS else 0)
            for ts, pos, speed in points:
                db.add(TruckLocationHistory(
                    truck_id=truck.id, latitude=pos[0], longitude=pos[1],
                    speed=speed, heading=bearing(here, dest), recorded_at=ts,
                ))
            here = points[-1][1]

        # Its own consumption, not the fleet's, so a thirsty truck stays thirsty.
        rates[str(truck.id)] = THIRSTY_TRUCKS.get(idx) or random.uniform(*NORMAL_CONSUMPTION)

    await db.commit()

    # ── The fuel those kilometres burned ──────────────────────────────────
    #
    # Sized from what ``scan_tracks`` measures, not from the ping distances
    # summed above. The two differ — the analytics pass drops the near-zero
    # speed clusters a parked truck emits, and this seed's raw sum does not —
    # and the digest prints both litres and kilometres on adjacent lines. Sized
    # the naive way they read as 58 L/100 km, which is the first arithmetic a
    # fleet owner in the room does and the first number that loses them.
    now = datetime.now(timezone.utc)
    week_start = now - timedelta(days=LEAKAGE_WINDOW_DAYS)
    tracks = await scan_tracks(db, week_start, now, org.id)
    # Yesterday measured on its own, so its fill can be sized from the distance
    # the digest will report beside it. Splitting the week's litres evenly
    # instead put a third of the fuel against a sixth of the kilometres, and the
    # digest's two adjacent lines divided out to 75 L/100 km.
    day_start_utc, day_end_utc = _day_bounds_utc(day)
    day_tracks = await scan_tracks(db, day_start_utc, day_end_utc, org.id)

    driven_km = 0.0
    fills = 0
    for truck in trucks:
        track = tracks.get(str(truck.id))
        km = float(track.distance_km) if track else 0.0
        if km <= 0:
            continue
        driven_km += km

        rate = rates.get(str(truck.id)) or random.uniform(*NORMAL_CONSUMPTION)
        day_track = day_tracks.get(str(truck.id))
        day_km = min(km, float(day_track.distance_km) if day_track else 0.0)
        truck.mileage = float(truck.mileage) + km

        # Two buckets, each sized from the distance it belongs to: yesterday's
        # fill covers yesterday, the earlier fills cover the rest of the week.
        day_liters = round(day_km * rate / 100.0, 1)
        earlier_liters = max(0.0, (km - day_km) * rate / 100.0)
        earlier_fills = max(1, RECENT_JOURNEYS - 1)

        # Split across the week rather than one implausible tanker-sized fill:
        # the fraud heuristics compare each row against the one before it, and a
        # single weekly fill would look like the very anomaly this is not.
        for n in range(RECENT_JOURNEYS):
            is_yesterday = n == RECENT_JOURNEYS - 1
            liters = (
                day_liters if is_yesterday
                else round(earlier_liters / earlier_fills * random.uniform(0.9, 1.1), 1)
            )
            if liters <= 0:
                continue
            price = float(random.randint(*D.DIESEL_PRICE_UZS))
            db.add(FuelLog(
                truck_id=truck.id,
                liters=liters,
                cost_per_liter=price,
                total_cost=round(liters * price, 2),
                mileage_at_fill=round(
                    float(truck.mileage) - km * (RECENT_JOURNEYS - 1 - n) / RECENT_JOURNEYS, 0
                ),
                fuel_station=random.choice(D.FUEL_STATIONS_UZ),
                # Newest fill lands on yesterday, for the same reason the last
                # leg does: the digest totals one day, and a fleet that drove
                # yesterday and bought no diesel reads as broken.
                filled_at=(
                    start + timedelta(hours=random.uniform(2, 10))
                    if is_yesterday
                    else now - timedelta(
                        days=(LEAKAGE_WINDOW_DAYS - 2) * (RECENT_JOURNEYS - 1 - n) / RECENT_JOURNEYS,
                        hours=random.uniform(1, 9),
                    )
                ),
            ))
            fills += 1

    # ── Loads that were signed for yesterday ──────────────────────────────
    #
    # Re-timed rather than generated: these trips already exist, already have
    # a rate, a truck and a driver, and already appear in the 60-day history.
    # Only the moment they were delivered moves.
    delivered = [t for t in trips if t.status == TripStatus.delivered and t.delivered_at]
    delivered.sort(key=lambda t: t.delivered_at, reverse=True)
    revenue = 0.0
    for offset, trip in enumerate(delivered[:YESTERDAY_DELIVERIES]):
        trip.delivered_at = start + timedelta(hours=9 + offset * 3, minutes=random.randint(0, 50))
        revenue += float(trip.rate)

        for _ in range(random.randint(2, 4)):
            category = random.choice(list(ExpenseCategory))
            low, high = EXPENSE_RANGES_UZS[category]
            db.add(DriverExpense(
                driver_id=trip.driver_id,
                truck_id=trip.truck_id,
                trip_id=trip.id,
                category=category,
                amount=round(random.uniform(low, high), 2),
                note=f"{trip.origin_name} → {trip.destination_name} yo'lida",
                spent_at=day,
            ))

    await db.commit()
    print(f"  oxirgi hafta: {driven_km:,.0f} km, {fills} ta quyish · "
          f"kecha ({day.isoformat()}): "
          f"{len(delivered[:YESTERDAY_DELIVERIES])} ta yetkazilgan reys "
          f"({revenue/1_000_000:,.1f} mln so'm)")


# --------------------------------------------------------------------------- #
# Driver expenses + trip expense reports ("yo'l varaqasi")                     #
# --------------------------------------------------------------------------- #

EXPENSE_RANGES_UZS = {
    ExpenseCategory.food: (60_000, 220_000),
    ExpenseCategory.toll: (150_000, 900_000),
    ExpenseCategory.parking: (40_000, 180_000),
    ExpenseCategory.fine: (300_000, 2_600_000),
    ExpenseCategory.repair: (500_000, 6_400_000),
    ExpenseCategory.lodging: (120_000, 480_000),
    ExpenseCategory.customs: (800_000, 5_800_000),
    ExpenseCategory.other: (50_000, 400_000),
}


async def seed_driver_expenses(db, trips: list[Trip]) -> None:
    count = 0
    for trip in trips:
        if trip.status != TripStatus.delivered or not trip.started_at:
            continue
        for _ in range(random.randint(2, 6)):
            category = random.choice(list(ExpenseCategory))
            low, high = EXPENSE_RANGES_UZS[category]
            db.add(DriverExpense(
                driver_id=trip.driver_id,
                truck_id=trip.truck_id,
                trip_id=trip.id,
                category=category,
                amount=round(random.uniform(low, high), 2),
                note=f"{trip.origin_name} → {trip.destination_name} yo'lida",
                spent_at=(trip.started_at + timedelta(days=random.randint(0, 3))).date(),
            ))
            count += 1
    await db.commit()
    print(f"  driver expenses: {count}")


FUEL_ROW_COUNT = 4


async def seed_trip_reports(db, org: Organization, trucks: list[Truck],
                            drivers: list[Driver], trips: list[Trip]) -> None:
    """Fill the paper-form replacement for a handful of finished long hauls."""
    truck_by_id = {t.id: t for t in trucks}
    driver_by_id = {d.id: d for d in drivers}

    long_hauls = [
        t for t in trips
        if t.status == TripStatus.delivered and (t.planned_distance_km or 0) > 800
    ][:6]

    for trip in long_hauls:
        truck = truck_by_id.get(trip.truck_id)
        driver = driver_by_id.get(trip.driver_id)
        odometer_out = float(truck.mileage) - random.uniform(3_000, 40_000) if truck else 0.0

        report = TripExpenseReport(
            id=uuid.uuid4(),
            org_id=org.id,
            trip_id=trip.id,
            plate_number=truck.plate_number if truck else None,
            driver_name=driver.name if driver else None,
            report_date=trip.delivered_at.date() if trip.delivered_at else date.today(),
            odometer_out=round(odometer_out, 0),
            odometer_in=round(odometer_out + float(trip.planned_distance_km or 0) * 2, 0),
            fuel_at_garage=round(random.uniform(180, 420), 1),
            route_text=f"{trip.origin_name} → {trip.destination_name} → {trip.origin_name}",
            exchange_rate_note="1 USD = 12 850 UZS (reys kunidagi kurs)",
            money_usd=round(random.uniform(1_200, 3_400), 2),
            money_uzs=round(random.uniform(3_000_000, 9_000_000), 2),
            money_kzt=round(random.uniform(80_000, 260_000), 2),
            money_rub=round(random.uniform(20_000, 70_000), 2),
            usd_to_kzt_given=400, usd_to_kzt_received=round(400 * 512, 2),
            usd_to_rub_given=300, usd_to_rub_received=round(300 * 92, 2),
            border_departure_at=trip.started_at + timedelta(hours=random.uniform(8, 20)) if trip.started_at else None,
            border_arrival_at=trip.started_at + timedelta(hours=random.uniform(21, 44)) if trip.started_at else None,
            electronic_pass_note="E-permit olindi",
            electronic_queue_note="CarGoRuqsat navbati: 14-o'rin",
            insurance_rf=round(random.uniform(45, 120), 2),
            insurance_kz=round(random.uniform(20, 60), 2),
            dollar_return=round(random.uniform(50, 480), 2),
            driver_comment="Chegarada navbat uzoq bo'ldi, qolgan yo'l muammosiz.",
            status=TripReportStatus.submitted,
            submitted_at=trip.delivered_at,
        )
        db.add(report)

        for row_no in range(1, FUEL_ROW_COUNT + 1):
            kz_l = round(random.uniform(120, 320), 1)
            rf_l = round(random.uniform(150, 420), 1)
            db.add(TripFuelRow(
                report_id=report.id,
                row_no=row_no,
                kz_liters=kz_l, kz_amount=round(kz_l * random.uniform(255, 300), 2),
                rf_liters=rf_l, rf_amount=round(rf_l * random.uniform(58, 72), 2),
                doha_liters=round(random.uniform(0, 180), 1), doha_amount=round(random.uniform(0, 2_400_000), 2),
                e1card_liters=round(random.uniform(0, 240), 1), e1card_amount=round(random.uniform(0, 3_100_000), 2),
            ))

        country_categories = {
            TripReportCountry.kz: [
                TripReportExpenseCategory.platon, TripReportExpenseCategory.food,
                TripReportExpenseCategory.traffic_police, TripReportExpenseCategory.parking,
                TripReportExpenseCategory.adblue,
            ],
            TripReportCountry.ru: [
                TripReportExpenseCategory.platon, TripReportExpenseCategory.food,
                TripReportExpenseCategory.fine, TripReportExpenseCategory.shower,
                TripReportExpenseCategory.spare_parts,
            ],
            TripReportCountry.uz: [
                TripReportExpenseCategory.groceries, TripReportExpenseCategory.taxi,
                TripReportExpenseCategory.carwash, TripReportExpenseCategory.parking_paperwork,
                TripReportExpenseCategory.repair,
            ],
        }
        for country, categories in country_categories.items():
            scale = {TripReportCountry.kz: 40_000, TripReportCountry.ru: 8_000,
                     TripReportCountry.uz: 400_000}[country]
            for category in categories:
                db.add(TripCountryExpenseLine(
                    report_id=report.id,
                    country=country,
                    category=category,
                    amount=round(random.uniform(0.4, 4.5) * scale, 2),
                ))

    await db.commit()
    print(f"  trip expense reports (yo'l varaqasi): {len(long_hauls)}")


async def seed_shifts(db, trucks: list[Truck], drivers: list[Driver]) -> None:
    now = datetime.now(timezone.utc)
    count = 0
    for idx, driver in enumerate(drivers):
        truck = trucks[idx] if idx < len(trucks) else None
        for d in range(random.randint(4, 9)):
            started = now - timedelta(days=d * 3 + random.randint(0, 2), hours=random.randint(4, 10))
            active = d == 0 and idx < 6
            db.add(Shift(
                driver_id=driver.id,
                truck_id=truck.id if truck else None,
                status=ShiftStatus.active if active else ShiftStatus.ended,
                started_at=started,
                ended_at=None if active else started + timedelta(hours=random.uniform(7, 12)),
                start_mileage=float(truck.mileage) - random.uniform(2_000, 30_000) if truck else None,
                end_mileage=float(truck.mileage) - random.uniform(0, 1_900) if truck and not active else None,
            ))
            count += 1
    await db.commit()
    print(f"  shifts: {count}")


# --------------------------------------------------------------------------- #
# Main                                                                         #
# --------------------------------------------------------------------------- #

async def main(reset: bool, password: str) -> None:
    random.seed(2026)  # reproducible demo
    async with SessionLocal() as db:
        print(f"Seeding demo tenant '{D.ORG_NAME}'...")
        org = await seed_org(db)
        if reset:
            await reset_org(db, org)

        await seed_users(db, org, password)
        await seed_geofences(db, org)
        trucks = await seed_trucks(db, org)
        drivers = await seed_drivers(db, org, trucks)
        km_by_truck = await seed_gps(db, trucks)
        await seed_fuel(db, trucks, km_by_truck)
        await seed_maintenance(db, trucks)
        trips = await seed_trips(db, org, trucks, drivers)
        await link_fuel_to_trips(db, org)
        await seed_driver_expenses(db, trips)
        await seed_trip_reports(db, org, trucks, drivers, trips)
        await seed_shifts(db, trucks, drivers)
        # Yesterday before the live pose: it appends GPS history, and the pose
        # reads the *trip* rather than the history, so the order only matters
        # for the mileage it bumps.
        await seed_yesterday(db, org, trucks, trips)
        # Last, because it overrides both the random truck status from
        # seed_trucks and the random live position from seed_gps.
        await align_live_positions(db, trips)

    print("\nTayyor. Kirish:")
    for email, role in D.DEMO_USERS:
        print(f"  {email}   ({role})")
    print("  parol: DEMO_PASSWORD dan olindi")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed the Uzbek demo tenant.")
    parser.add_argument("--reset", action="store_true",
                        help="Delete this org's existing rows first (other tenants untouched)")
    args = parser.parse_args()

    # Fail before touching the database rather than falling back to a default.
    # A built-in default would be the same on every deployment, which for a
    # tenant that sits on production next to paying customers is the same thing
    # as having no password at all.
    demo_password = os.environ.get("DEMO_PASSWORD", "")
    if len(demo_password) < 8:
        parser.error(
            "DEMO_PASSWORD environment variable is required (min 8 chars).\n"
            "  Example: DEMO_PASSWORD='...' python seed_demo_uz.py"
        )

    asyncio.run(main(reset=args.reset, password=demo_password))
