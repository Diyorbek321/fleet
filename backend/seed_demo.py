"""Seed realistic demo data for Sunday investor/owner demo.

Creates:
- Admin + manager users
- 8 trucks with realistic US makes/models/plates
- 8 drivers with realistic names, phones, license info
- Active driver-truck assignments
- 30 days of GPS history per truck (routes between US cities)
- Current live-position rows
- 90 days of fuel logs per truck (~2 fills/week)
- 60 days of maintenance records per truck
- Service intervals (oil, tires, brakes) with realistic next-service dates

Run:
    python seed_demo.py            # populate (idempotent — wipes demo rows first)
    python seed_demo.py --keep     # add to existing data without wiping

Then run live-movement simulator separately:
    python simulate_live.py
"""
from __future__ import annotations

import argparse
import asyncio
import math
import random
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import delete, select

from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models.organizations import Organization
from app.models.drivers import Driver, DriverAssignment
from app.models.enums import (
    DriverStatus,
    ServiceStatus,
    ServiceType,
    TruckStatus,
    UserRole,
)
from app.models.maintenance import FuelLog, MaintenanceRecord, ServiceInterval
from app.models.trucks import Truck, TruckLocation, TruckLocationHistory
from app.models.users import User


# --------------------------------------------------------------------------- #
# Realistic data pools                                                        #
# --------------------------------------------------------------------------- #

TRUCKS = [
    {"name": "Eagle 01", "plate": "TX-4821", "model": "Freightliner Cascadia", "year": 2022},
    {"name": "Eagle 02", "plate": "TX-4822", "model": "Peterbilt 579",          "year": 2021},
    {"name": "Eagle 03", "plate": "TX-4823", "model": "Kenworth T680",          "year": 2023},
    {"name": "Eagle 04", "plate": "TX-4824", "model": "Volvo VNL 860",          "year": 2020},
    {"name": "Eagle 05", "plate": "TX-4825", "model": "Mack Anthem",            "year": 2022},
    {"name": "Eagle 06", "plate": "TX-4826", "model": "International LT",       "year": 2021},
    {"name": "Eagle 07", "plate": "TX-4827", "model": "Freightliner Cascadia",  "year": 2023},
    {"name": "Eagle 08", "plate": "TX-4828", "model": "Peterbilt 389",          "year": 2019},
]

DRIVERS = [
    {"name": "Michael Rodriguez", "phone": "+1-512-555-0142", "license": "TX-DL-8821445", "email": "m.rodriguez@fleetdemo.com"},
    {"name": "James Patterson",   "phone": "+1-512-555-0198", "license": "TX-DL-7745213", "email": "j.patterson@fleetdemo.com"},
    {"name": "David Chen",        "phone": "+1-512-555-0167", "license": "TX-DL-9912088", "email": "d.chen@fleetdemo.com"},
    {"name": "Robert Williams",   "phone": "+1-512-555-0123", "license": "TX-DL-6634009", "email": "r.williams@fleetdemo.com"},
    {"name": "Carlos Martinez",   "phone": "+1-512-555-0154", "license": "TX-DL-5521776", "email": "c.martinez@fleetdemo.com"},
    {"name": "Anthony Brooks",    "phone": "+1-512-555-0189", "license": "TX-DL-4498332", "email": "a.brooks@fleetdemo.com"},
    {"name": "Daniel Kim",        "phone": "+1-512-555-0176", "license": "TX-DL-3387220", "email": "d.kim@fleetdemo.com"},
    {"name": "Marcus Johnson",    "phone": "+1-512-555-0145", "license": "TX-DL-2276119", "email": "m.johnson@fleetdemo.com"},
]

# Texas corridor — Dallas, Houston, San Antonio, Austin, El Paso area
ROUTES = [
    # (start_lat, start_lon, end_lat, end_lon, label)
    (32.7767, -96.7970, 29.7604, -95.3698, "Dallas → Houston"),
    (29.7604, -95.3698, 29.4241, -98.4936, "Houston → San Antonio"),
    (29.4241, -98.4936, 30.2672, -97.7431, "San Antonio → Austin"),
    (30.2672, -97.7431, 32.7767, -96.7970, "Austin → Dallas"),
    (31.7619, -106.4850, 29.4241, -98.4936, "El Paso → San Antonio"),
    (32.7767, -96.7970, 31.7619, -106.4850, "Dallas → El Paso"),
    (30.2672, -97.7431, 29.7604, -95.3698, "Austin → Houston"),
    (29.4241, -98.4936, 32.7767, -96.7970, "San Antonio → Dallas"),
]

FUEL_STATIONS = ["Pilot Flying J", "Love's Travel Stop", "TA Travel Center", "Buc-ee's", "Shell", "Chevron"]
SERVICE_VENDORS = ["TruckPro Service Center", "Rush Truck Center", "Speedco", "Bruckner's", "Independent Mechanic"]
MAINT_NOTES = [
    "Routine service, no issues found.",
    "Minor adjustment, replaced filter.",
    "Scheduled DOT inspection — passed.",
    "Replaced worn belt during inspection.",
    "Topped off all fluids, tires rotated.",
    "Brake pads at 60% — flagged for next service.",
]


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #

def interpolate(start: tuple[float, float], end: tuple[float, float], t: float) -> tuple[float, float]:
    """Linear interpolation along a great-ish-circle (good enough for Texas)."""
    return (
        start[0] + (end[0] - start[0]) * t,
        start[1] + (end[1] - start[1]) * t,
    )


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    R = 6371.0
    lat1, lon1, lat2, lon2 = map(math.radians, [a[0], a[1], b[0], b[1]])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def jitter(lat: float, lon: float, scale: float = 0.005) -> tuple[float, float]:
    return (lat + random.uniform(-scale, scale), lon + random.uniform(-scale, scale))


# --------------------------------------------------------------------------- #
# Wipe                                                                        #
# --------------------------------------------------------------------------- #

async def wipe_demo(db) -> None:
    print("Wiping existing demo rows...")
    await db.execute(delete(TruckLocationHistory))
    await db.execute(delete(TruckLocation))
    await db.execute(delete(FuelLog))
    await db.execute(delete(MaintenanceRecord))
    await db.execute(delete(ServiceInterval))
    await db.execute(delete(DriverAssignment))
    await db.execute(delete(Driver))
    await db.execute(delete(Truck))
    await db.commit()


# --------------------------------------------------------------------------- #
# Seeders                                                                     #
# --------------------------------------------------------------------------- #

async def seed_org(db) -> Organization:
    """Get-or-create the demo organization that owns all seeded data."""
    org = (
        await db.execute(select(Organization).where(Organization.name == "Fleet Demo Co"))
    ).scalar_one_or_none()
    if org is None:
        org = Organization(id=uuid.uuid4(), name="Fleet Demo Co")
        db.add(org)
        await db.commit()
        await db.refresh(org)
    print(f"  org: {org.name} ({org.id})")
    return org


async def seed_users(db, org: Organization) -> None:
    accounts = [
        ("owner@fleetdemo.com",   "demo1234", UserRole.admin),
        ("manager@fleetdemo.com", "demo1234", UserRole.manager),
    ]
    for email, pw, role in accounts:
        existing = await db.execute(select(User).where(User.email == email))
        if existing.scalar_one_or_none():
            continue
        db.add(User(org_id=org.id, email=email, password_hash=hash_password(pw), role=role))
    await db.commit()
    print("  users: owner@fleetdemo.com / manager@fleetdemo.com  (password: demo1234)")


async def seed_trucks(db, org: Organization) -> list[Truck]:
    trucks: list[Truck] = []
    for spec in TRUCKS:
        t = Truck(
            id=uuid.uuid4(),
            org_id=org.id,
            name=spec["name"],
            plate_number=spec["plate"],
            model=spec["model"],
            year=spec["year"],
            status=random.choice([TruckStatus.moving, TruckStatus.moving, TruckStatus.stopped, TruckStatus.idle]),
            fuel_level=round(random.uniform(35, 95), 1),
            mileage=round(random.uniform(80_000, 320_000), 0),
        )
        db.add(t)
        trucks.append(t)
    await db.commit()
    print(f"  trucks: {len(trucks)}")
    return trucks


async def seed_drivers_and_assignments(db, org: Organization, trucks: list[Truck]) -> list[Driver]:
    drivers: list[Driver] = []
    today = date.today()
    for spec in DRIVERS:
        d = Driver(
            id=uuid.uuid4(),
            org_id=org.id,
            name=spec["name"],
            phone=spec["phone"],
            email=spec["email"],
            license_number=spec["license"],
            license_expiry=today + timedelta(days=random.randint(60, 900)),
            status=DriverStatus.active,
        )
        db.add(d)
        drivers.append(d)
    await db.commit()

    # 1:1 assignment for first N drivers/trucks
    for driver, truck in zip(drivers, trucks):
        db.add(DriverAssignment(
            id=uuid.uuid4(),
            driver_id=driver.id,
            truck_id=truck.id,
            assigned_at=datetime.now(timezone.utc) - timedelta(days=random.randint(30, 400)),
        ))
    await db.commit()
    print(f"  drivers: {len(drivers)} (all assigned)")
    return drivers


async def seed_gps_history(db, trucks: list[Truck]) -> None:
    """30 days of GPS pings per truck. ~1 ping/15min during driving hours."""
    now = datetime.now(timezone.utc)
    total = 0
    for truck in trucks:
        # pick a route that loops; ~6 trips over 30 days
        for trip in range(6):
            route = random.choice(ROUTES)
            start = (route[0], route[1])
            end = (route[2], route[3])
            trip_start = now - timedelta(days=30 - trip * 5, hours=random.randint(0, 8))
            # ~24 pings per trip (representing 6h drive at 15-min intervals)
            steps = 24
            for i in range(steps):
                t = i / (steps - 1)
                lat, lon = interpolate(start, end, t)
                lat, lon = jitter(lat, lon, 0.01)
                speed = round(random.uniform(85, 110), 1) if 0.05 < t < 0.95 else round(random.uniform(0, 15), 1)
                heading = round(random.uniform(0, 360), 1)
                recorded = trip_start + timedelta(minutes=15 * i)
                db.add(TruckLocationHistory(
                    truck_id=truck.id,
                    latitude=lat, longitude=lon,
                    speed=speed, heading=heading,
                    recorded_at=recorded,
                ))
                total += 1

        # current "live" location — last point of last trip
        route = random.choice(ROUTES)
        cur_lat, cur_lon = interpolate((route[0], route[1]), (route[2], route[3]), random.uniform(0.2, 0.8))
        cur_lat, cur_lon = jitter(cur_lat, cur_lon, 0.005)
        cur_speed = round(random.uniform(60, 100), 1) if truck.status == TruckStatus.moving else 0.0
        db.add(TruckLocation(
            truck_id=truck.id,
            latitude=cur_lat, longitude=cur_lon,
            speed=cur_speed, heading=round(random.uniform(0, 360), 1),
            address=random.choice(["I-35 N", "I-10 W", "US-290 E", "I-45 S", "TX-130 N"]),
            recorded_at=now,
        ))
    await db.commit()
    print(f"  gps history pings: {total} (+ {len(trucks)} live positions)")


async def seed_fuel_logs(db, trucks: list[Truck]) -> None:
    """~2 fills/week for 90 days — strong fuel-cost story."""
    now = datetime.now(timezone.utc)
    total = 0
    for truck in trucks:
        # base MPG varies by truck (semis are 5-8 mpg loaded)
        base_mpg = random.uniform(5.5, 7.8)
        mileage_at_start = float(truck.mileage) - random.uniform(15_000, 25_000)
        running_mileage = mileage_at_start

        for fill_idx in range(26):  # ~26 fills over 90 days
            days_ago = 90 - fill_idx * (90 / 26)
            filled_at = now - timedelta(days=days_ago, hours=random.randint(0, 23))

            # diesel ~$3.60-$4.20/gal in TX. liters used because schema says liters but we're treating as gallons in UI.
            # Convert: store gallons in liters field for demo (US trucking owners think gallons).
            # We'll keep "liters" as the column but populate gallon-scale numbers — frontend already shows it as fuel.
            gallons = round(random.uniform(140, 220), 1)  # typical fill on big tanks
            price = round(random.uniform(3.55, 4.25), 3)
            total_cost = round(gallons * price, 2)

            miles_driven = gallons * base_mpg * random.uniform(0.92, 1.08)
            running_mileage += miles_driven

            db.add(FuelLog(
                truck_id=truck.id,
                liters=gallons,           # treated as gallons in UI
                cost_per_liter=price,     # treated as $/gallon
                total_cost=total_cost,
                mileage_at_fill=round(running_mileage, 0),
                fuel_station=random.choice(FUEL_STATIONS),
                filled_at=filled_at,
            ))
            total += 1
    await db.commit()
    print(f"  fuel logs: {total}")


async def seed_maintenance(db, trucks: list[Truck]) -> None:
    """Service intervals + 60d maintenance history per truck."""
    today = date.today()
    record_count = 0
    interval_count = 0

    for truck in trucks:
        cur_mileage = float(truck.mileage)

        # Service intervals — oil, tires, brakes
        intervals_spec = [
            (ServiceType.oil_change,        25_000,  180,   8_000,    60),  # interval_km, interval_days, since_km, since_days
            (ServiceType.tire_rotation,     50_000,  365,   18_000,  140),
            (ServiceType.brake_inspection,  80_000,  730,   35_000,  220),
        ]
        for st, ikm, idays, since_km, since_days in intervals_spec:
            last_km = cur_mileage - since_km
            last_dt = today - timedelta(days=since_days)
            next_km = last_km + ikm
            next_dt = last_dt + timedelta(days=idays)

            status = ServiceStatus.scheduled
            if today >= next_dt or cur_mileage >= next_km:
                status = ServiceStatus.overdue

            db.add(ServiceInterval(
                truck_id=truck.id,
                service_type=st,
                interval_km=ikm,
                interval_days=idays,
                last_service_date=last_dt,
                last_service_mileage=last_km,
                next_service_date=next_dt,
                next_service_mileage=next_km,
                status=status,
            ))
            interval_count += 1

        # Maintenance history — 4-7 records per truck over last year
        for _ in range(random.randint(4, 7)):
            performed = today - timedelta(days=random.randint(7, 360))
            st = random.choice(list(ServiceType))
            cost = round({
                ServiceType.oil_change: random.uniform(180, 320),
                ServiceType.tire_rotation: random.uniform(80, 180),
                ServiceType.brake_inspection: random.uniform(450, 1200),
                ServiceType.engine_service: random.uniform(800, 2400),
                ServiceType.transmission: random.uniform(1500, 4500),
                ServiceType.general: random.uniform(120, 600),
            }[st], 2)

            db.add(MaintenanceRecord(
                truck_id=truck.id,
                service_type=st,
                description=f"{st.value.replace('_', ' ').title()} service",
                cost=cost,
                mileage_at_service=cur_mileage - random.uniform(500, 18_000),
                performed_by=random.choice(SERVICE_VENDORS),
                performed_at=performed,
                notes=random.choice(MAINT_NOTES),
            ))
            record_count += 1

    await db.commit()
    print(f"  service intervals: {interval_count}")
    print(f"  maintenance records: {record_count}")


# --------------------------------------------------------------------------- #
# Main                                                                        #
# --------------------------------------------------------------------------- #

async def main(keep: bool) -> None:
    random.seed(42)  # reproducible demo
    async with SessionLocal() as db:
        if not keep:
            await wipe_demo(db)

        print("Seeding demo data...")
        org = await seed_org(db)
        await seed_users(db, org)
        trucks = await seed_trucks(db, org)
        await seed_drivers_and_assignments(db, org, trucks)
        await seed_gps_history(db, trucks)
        await seed_fuel_logs(db, trucks)
        await seed_maintenance(db, trucks)

    print("\nDone. Login with:")
    print("  owner@fleetdemo.com / demo1234   (admin)")
    print("  manager@fleetdemo.com / demo1234 (manager)")
    print("\nFor live truck movement on the map, run:  python simulate_live.py")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep", action="store_true", help="Don't wipe existing demo rows first")
    args = parser.parse_args()
    asyncio.run(main(keep=args.keep))
