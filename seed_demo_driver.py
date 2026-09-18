"""Give the Uzbek demo tenant a driver login, for the mobile walkthrough.

``seed_demo_uz.py`` builds the fleet but creates no driver account: the demo
users it makes are the admin and the dispatcher, and a driver login is normally
issued per person from the manager panel.

Run this after seeding to get one:

    DEMO_PASSWORD='...' python seed_demo_uz.py --reset
    DEMO_PASSWORD='...' python seed_demo_driver.py

It picks a driver who has a trip in progress, so the mobile app opens on
something worth showing rather than an empty screen.

Idempotent, and safe to re-run after ``--reset``. That matters: the reset
deletes ``drivers`` rows, and ``users.driver_id`` is ``ON DELETE SET NULL``, so
an existing login survives the wipe pointing at nobody — every ``/api/me/*``
call then returns 403 and the app looks broken for a reason nothing on screen
explains. Re-running re-points it at a live driver.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import select

import demo_data_uz as D
from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models.drivers import Driver
from app.models.enums import TripStatus, UserRole
from app.models.organizations import Organization
from app.models.trips import Trip
from app.models.users import User

# Statuses that mean "this driver is out on the road right now".
LIVE = (TripStatus.en_route, TripStatus.at_border, TripStatus.loading, TripStatus.planned)


async def main(email: str, password: str) -> None:
    async with SessionLocal() as db:
        org = (
            await db.execute(select(Organization).where(Organization.name == D.ORG_NAME))
        ).scalar_one_or_none()
        if org is None:
            raise SystemExit(f"organization {D.ORG_NAME!r} not found — run seed_demo_uz.py first")

        # A driver with a trip under way, so the app opens on real work.
        driver = (
            await db.execute(
                select(Driver)
                .join(Trip, Trip.driver_id == Driver.id)
                .where(Driver.org_id == org.id, Trip.status.in_(LIVE))
                .limit(1)
            )
        ).scalars().first()
        if driver is None:
            driver = (
                await db.execute(select(Driver).where(Driver.org_id == org.id).limit(1))
            ).scalars().first()
        if driver is None:
            raise SystemExit("no drivers in the demo organization — run seed_demo_uz.py first")

        user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
        if user is None:
            user = User(
                org_id=org.id,
                email=email,
                password_hash=hash_password(password),
                role=UserRole.driver,
                driver_id=driver.id,
            )
            db.add(user)
            action = "created"
        else:
            # Re-point rather than skip: after a --reset the row is intact but
            # its driver_id is NULL, which is exactly the case this exists for.
            user.org_id = org.id
            user.role = UserRole.driver
            user.driver_id = driver.id
            user.password_hash = hash_password(password)
            action = "re-linked"

        await db.commit()

    print(f"driver login {action}: {email}  →  {driver.name} ({driver.license_number})")
    print("password: taken from DEMO_PASSWORD")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create the demo driver login.")
    parser.add_argument("--email", default="haydovchi@silkroad.uz")
    args = parser.parse_args()

    # Same contract as seed_demo_uz.py: no default, because this runs against a
    # tenant that sits on production next to paying customers.
    demo_password = os.environ.get("DEMO_PASSWORD", "")
    if len(demo_password) < 8:
        parser.error("DEMO_PASSWORD environment variable is required (min 8 chars).")

    asyncio.run(main(args.email, demo_password))
