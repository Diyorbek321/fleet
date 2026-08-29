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
  map and the trips board are not all-green.

**Scope**: every write is confined to this one organization. Other tenants —
including the real "Default Fleet" data on production — are never read or
touched, and ``--reset`` only deletes rows belonging to the demo org.

Run (DEMO_PASSWORD is required — see ``demo_data_uz.py``):
    DEMO_PASSWORD='...' python seed_demo_uz.py            # create/top-up the demo org
    DEMO_PASSWORD='...' python seed_demo_uz.py --reset    # wipe the demo org's rows first, then seed
"""
from __future__ import annotations

import argparse
import asyncio
import math
import os
import random
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
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
from app.models.organizations import Organization
from app.models.trip_reports import TripCountryExpenseLine, TripExpenseReport, TripFuelRow
from app.models.trips import Trip, TripEvent
from app.models.trucks import Truck, TruckLocation, TruckLocationHistory
from app.models.users import User

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
    for email, role in D.DEMO_USERS:
        existing = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
        if existing:
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
            # Spread across days 28→4 so every fill lands inside the 30-day
            # analytics window (a fill exactly on the boundary gets dropped).
            filled_at = now - timedelta(days=28 - f * (24 / max(fills - 1, 1)), hours=random.randint(0, 20))
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


async def seed_trips(db, org: Organization, trucks: list[Truck], drivers: list[Driver]) -> list[Trip]:
    now = datetime.now(timezone.utc)
    trips: list[Trip] = []
    counter = 1

    for idx, truck in enumerate(trucks):
        driver = drivers[idx] if idx < len(drivers) else random.choice(drivers)
        for j in range(random.randint(6, 9)):
            origin_name, dest_name, distance_km, rate, international = random.choice(D.CORRIDORS)
            origin, dest = D.CITIES[origin_name], D.CITIES[dest_name]
            cargo, weight, reefer = random.choice(D.CARGO)

            days_ago = random.randint(2, TRIP_DAYS)
            scheduled_start = now - timedelta(days=days_ago, hours=random.randint(0, 12))
            duration_h = distance_km / 55.0 + (18 if international else 4)
            scheduled_end = scheduled_start + timedelta(hours=duration_h)

            # The last trip of the first six trucks is still running — so the
            # live map and the trips board are not uniformly "delivered".
            is_tail = (j == 2) and idx < len(ACTIVE_TAIL)
            status = ACTIVE_TAIL[idx] if is_tail else TripStatus.delivered

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
