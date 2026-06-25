"""Continuously update truck GPS positions to make the map look alive during demo.

Each truck slowly walks along a route; positions update every ~3 seconds and are
broadcast through the existing WebSocket layer (if other code subscribes to
TruckLocation changes via the API). For maximum compatibility, this writes
directly to the DB so the /api/trucks endpoint and live-locations queries
return fresh data on every refresh.

Run alongside the backend:
    python simulate_live.py

Stop with Ctrl-C.
"""
from __future__ import annotations

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

from app.core.database import SessionLocal
from app.models.enums import TruckStatus
from app.models.trucks import Truck, TruckLocation, TruckLocationHistory


ROUTES = [
    ((32.7767, -96.7970), (29.7604, -95.3698)),  # Dallas → Houston
    ((29.7604, -95.3698), (29.4241, -98.4936)),  # Houston → SA
    ((29.4241, -98.4936), (30.2672, -97.7431)),  # SA → Austin
    ((30.2672, -97.7431), (32.7767, -96.7970)),  # Austin → Dallas
    ((32.7767, -96.7970), (31.7619, -106.4850)), # Dallas → El Paso
    ((30.2672, -97.7431), (29.7604, -95.3698)),  # Austin → Houston
]

TICK_SECONDS = 3.0
STEP_FRACTION = 0.0035  # how much of the route to advance per tick (~5 min route ≈ 1 tick)


def interp(a, b, t):
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def bearing(a, b):
    lat1, lon1, lat2, lon2 = map(math.radians, [a[0], a[1], b[0], b[1]])
    dlon = lon2 - lon1
    y = math.sin(dlon) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


class TruckSim:
    def __init__(self, truck_id, start_t: float):
        self.truck_id = truck_id
        self.route = random.choice(ROUTES)
        self.t = start_t
        self.speed = random.uniform(85, 105)

    def step(self):
        self.t += STEP_FRACTION * random.uniform(0.7, 1.3)
        if self.t >= 1.0:
            # arrive — pick a new route from current end
            new_route = random.choice(ROUTES)
            self.route = (self.route[1], new_route[1])
            self.t = 0.0
            self.speed = random.uniform(80, 105)
        lat, lon = interp(self.route[0], self.route[1], self.t)
        head = bearing(self.route[0], self.route[1])
        # tiny jitter to look organic
        lat += random.uniform(-0.0008, 0.0008)
        lon += random.uniform(-0.0008, 0.0008)
        return lat, lon, self.speed + random.uniform(-3, 3), head


async def main():
    print("Starting live simulator. Ctrl-C to stop.")
    sims: dict = {}

    async with SessionLocal() as db:
        res = await db.execute(select(Truck))
        trucks = res.scalars().all()
        if not trucks:
            print("No trucks found. Run seed_demo.py first.")
            return
        for t in trucks:
            sims[t.id] = TruckSim(t.id, random.random())
            t.status = TruckStatus.moving
        await db.commit()
        print(f"Simulating {len(sims)} trucks.")

    try:
        while True:
            async with SessionLocal() as db:
                for truck_id, sim in sims.items():
                    lat, lon, speed, heading = sim.step()
                    now = datetime.now(timezone.utc)

                    # update live location row (upsert manually)
                    res = await db.execute(select(TruckLocation).where(TruckLocation.truck_id == truck_id))
                    loc = res.scalar_one_or_none()
                    if loc:
                        loc.latitude = lat
                        loc.longitude = lon
                        loc.speed = speed
                        loc.heading = heading
                        loc.recorded_at = now
                    else:
                        db.add(TruckLocation(
                            truck_id=truck_id,
                            latitude=lat, longitude=lon,
                            speed=speed, heading=heading,
                            recorded_at=now,
                        ))

                    # also append to history for nice trails (every ~5 ticks)
                    if random.random() < 0.2:
                        db.add(TruckLocationHistory(
                            truck_id=truck_id,
                            latitude=lat, longitude=lon,
                            speed=speed, heading=heading,
                            recorded_at=now,
                        ))

                await db.commit()
            await asyncio.sleep(TICK_SECONDS)
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    asyncio.run(main())
