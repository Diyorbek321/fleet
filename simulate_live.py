"""Keep the demo tenant's trucks moving on the map, for the live walkthrough.

``seed_demo_uz.py`` writes each truck's last position a few minutes in the
past, which looks alive at seed time and stale by the afternoon. Seeding again
before the meeting would fix that and throw away the thirty days of history the
money screens are built on, so this walks the existing positions forward
instead: same trucks, same corridors, fresh timestamps.

Run it next to the backend and leave it running for the length of the demo:

    python simulate_live.py                  # demo org, visible movement
    python simulate_live.py --compress 300   # faster — good for a wide map
    python simulate_live.py --org "Default Fleet"

**Scope.** Only one organization's trucks are touched, and by default that is
the demo tenant. The previous version selected every ``Truck`` row in the
database, which on production means walking real customers' fleets across
Texas — their live map, their geofence events, their history.

**Which trucks.** Only the ones already ``moving``. A truck the seed parked in
the depot or put in the workshop stays there: a fleet where all twelve trucks
drive at once is the one detail on the map a fleet owner will not believe.

Time is compressed rather than faked: ``--compress N`` means one real second
advances the truck by N seconds of driving at its own speed. Nothing else about
the position is invented — the speed written to the row is the speed used to
move it.
"""
from __future__ import annotations

import argparse
import asyncio
import math
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import select

import demo_data_uz as D
from app.core.database import SessionLocal
from app.models.enums import TripStatus, TruckStatus
from app.models.organizations import Organization
from app.models.trips import Trip
from app.models.trucks import Truck, TruckLocation, TruckLocationHistory

TICK_SECONDS = 3.0
DEFAULT_COMPRESS = 180.0   # 1 real second = 3 simulated minutes
HISTORY_EVERY = 5          # append a trail point every N ticks
EARTH_KM = 6371.0

# The domestic corridors only. A Moskva run is 3 360 km of straight line that
# spends the whole demo somewhere over Qozog'iston, off the edge of the map the
# dispatcher is actually looking at.
ROUTES: list[tuple[tuple[float, float], tuple[float, float]]] = [
    (D.CITIES[origin], D.CITIES[dest])
    for origin, dest, _km, _rate, international in D.CORRIDORS
    if not international
]


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, [a[0], a[1], b[0], b[1]])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_KM * math.asin(math.sqrt(h))


def lerp(a: tuple[float, float], b: tuple[float, float], t: float) -> tuple[float, float]:
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def bearing(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lat2 = math.radians(a[0]), math.radians(b[0])
    dlon = math.radians(b[1] - a[1])
    y = math.sin(dlon) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def nearest_route(point: tuple[float, float]) -> tuple[tuple[float, float], tuple[float, float]]:
    """A corridor starting near where the truck already is.

    Picking at random would teleport every truck to a random city on the first
    tick, which is exactly the thing a fleet owner watches the map to catch.
    """
    return min(ROUTES, key=lambda route: haversine_km(point, route[0]))


class TruckSim:
    """One truck walking a corridor, carrying its own speed and progress."""

    def __init__(self, truck_id, start: tuple[float, float], compress: float,
                 route: tuple[tuple[float, float], tuple[float, float]] | None = None):
        self.truck_id = truck_id
        self.compress = compress
        # A truck with a running trip walks *that* trip's corridor. Falling
        # back to the nearest domestic route would drive a load booked for
        # Bishkek steadily towards Samarqand while the dispatcher board and the
        # cargo owner's Telegram message both still say Bishkek.
        self.origin, self.destination = route or nearest_route(start)
        # Resume from wherever the seed left the truck rather than from the
        # depot, so the first tick nudges it instead of jumping it.
        self.progress = self._closest_progress(start)
        self.speed_kmh = random.uniform(62, 88)

    def _closest_progress(self, point: tuple[float, float]) -> float:
        total = haversine_km(self.origin, self.destination)
        if total <= 0:
            return 0.0
        return min(0.95, max(0.0, haversine_km(self.origin, point) / total))

    def step(self) -> tuple[float, float, float, float]:
        total_km = haversine_km(self.origin, self.destination)
        km_this_tick = self.speed_kmh * (TICK_SECONDS * self.compress / 3600.0)
        self.progress += km_this_tick / total_km if total_km else 1.0

        if self.progress >= 1.0:
            # Arrived. Leave from here on a corridor that starts nearby, the
            # same way the truck would in the morning.
            self.origin, self.destination = nearest_route(self.destination)
            self.progress = 0.0
            self.speed_kmh = random.uniform(62, 88)

        lat, lng = lerp(self.origin, self.destination, self.progress)
        # A few hundred metres of wander, so a convoy on one corridor does not
        # render as a single marker.
        lat += random.uniform(-0.004, 0.004)
        lng += random.uniform(-0.004, 0.004)
        self.speed_kmh = max(45.0, min(95.0, self.speed_kmh + random.uniform(-2.5, 2.5)))
        return lat, lng, self.speed_kmh, bearing(self.origin, self.destination)


async def load_fleet(org_name: str) -> dict:
    """Build a simulator per moving truck in one organization."""
    async with SessionLocal() as db:
        org = (
            await db.execute(select(Organization).where(Organization.name == org_name))
        ).scalar_one_or_none()
        if org is None:
            raise SystemExit(f"organization {org_name!r} not found — run seed_demo_uz.py first")

        trucks = (
            await db.execute(
                select(Truck).where(
                    Truck.org_id == org.id, Truck.status == TruckStatus.moving
                )
            )
        ).scalars().all()
        if not trucks:
            raise SystemExit(
                f"no moving trucks in {org_name!r} — run seed_demo_uz.py --reset first"
            )

        # The corridor each truck is actually contracted to drive, when it has
        # one. ``en_route`` only: a trip still loading has its truck parked,
        # and those trucks are not simulated anyway.
        routes: dict = {}
        for trip in (
            await db.execute(
                select(Trip).where(Trip.org_id == org.id, Trip.status == TripStatus.en_route)
            )
        ).scalars().all():
            if trip.truck_id and trip.origin_lat is not None and trip.destination_lat is not None:
                routes[trip.truck_id] = (
                    (float(trip.origin_lat), float(trip.origin_lng)),
                    (float(trip.destination_lat), float(trip.destination_lng)),
                )

        starts: dict = {}
        for truck in trucks:
            location = (
                await db.execute(
                    select(TruckLocation).where(TruckLocation.truck_id == truck.id)
                )
            ).scalar_one_or_none()
            starts[truck.id] = (
                (float(location.latitude), float(location.longitude))
                if location
                else D.CITIES["Toshkent"]
            )
        return {
            "org": org.name,
            "trucks": [(t.id, t.name, starts[t.id], routes.get(t.id)) for t in trucks],
        }


async def run(org_name: str, compress: float) -> None:
    fleet = await load_fleet(org_name)
    sims = {
        truck_id: TruckSim(truck_id, start, compress, route)
        for truck_id, _name, start, route in fleet["trucks"]
    }
    on_trip = sum(1 for *_ , route in fleet["trucks"] if route)
    print(f"'{fleet['org']}' — {len(sims)} ta harakatdagi mashina "
          f"({on_trip} tasi o'z reysi yo'nalishida), {compress:.0f}x tezlikda.")
    print("To'xtatish: Ctrl-C")

    tick = 0
    while True:
        tick += 1
        async with SessionLocal() as db:
            for truck_id, sim in sims.items():
                lat, lng, speed, heading = sim.step()
                now = datetime.now(timezone.utc)

                location = (
                    await db.execute(
                        select(TruckLocation).where(TruckLocation.truck_id == truck_id)
                    )
                ).scalar_one_or_none()
                if location is None:
                    db.add(TruckLocation(
                        truck_id=truck_id, latitude=lat, longitude=lng,
                        speed=speed, heading=heading, recorded_at=now,
                    ))
                else:
                    location.latitude = lat
                    location.longitude = lng
                    location.speed = speed
                    location.heading = heading
                    location.recorded_at = now

                if tick % HISTORY_EVERY == 0:
                    db.add(TruckLocationHistory(
                        truck_id=truck_id, latitude=lat, longitude=lng,
                        speed=speed, heading=heading, recorded_at=now,
                    ))
            await db.commit()
        await asyncio.sleep(TICK_SECONDS)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Keep one org's trucks moving on the map.")
    parser.add_argument("--org", default=D.ORG_NAME,
                        help=f"Organization to simulate (default: {D.ORG_NAME!r})")
    parser.add_argument("--compress", type=float, default=DEFAULT_COMPRESS,
                        help="Seconds of driving per real second (default: %(default)s)")
    args = parser.parse_args()

    try:
        asyncio.run(run(args.org, args.compress))
    except KeyboardInterrupt:
        print("\nTo'xtatildi.")
