"""Seed a default admin user (and optional demo trucks), plus the platform superadmin.

Usage:
    python seed.py                    # creates admin + 3 demo trucks  (DEV ONLY)
    python seed.py --admin-only       # admin user only, no trucks     (DEV ONLY)
    python seed.py --superadmin-only  # platform superadmin only       ← use this on production
    python seed.py --reset            # delete existing admin first (won't touch other users)

**Never run the bare form against production.** It creates
``admin@example.com / password123`` as a full admin inside the first real
customer organization and drops demo trucks into their fleet. On a live box
always pass ``--superadmin-only``.

Env vars (all optional):
    SEED_ADMIN_EMAIL          default: admin@example.com
    SEED_ADMIN_PASSWORD       default: password123
    SEED_ADMIN_ROLE           default: admin
    SEED_SUPERADMIN_EMAIL     no default — set both to create the platform operator
    SEED_SUPERADMIN_PASSWORD  no default

The superadmin is the platform operator's own login (the console at
``/api/organizations`` used to onboard customer companies). It lives in an
organization named "Platform" that deliberately holds no fleet data — it exists
only because ``users.org_id`` is NOT NULL.

Idempotent: re-running won't duplicate the admin, the superadmin or demo trucks.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

# Make `app.*` importable when run as `python seed.py`
BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models.enums import UserRole
from app.models.organizations import Organization
from app.models.trucks import Truck
from app.models.users import User


async def _get_or_create_org(db, name: str = "Default Fleet") -> Organization:
    org = (
        await db.execute(select(Organization).where(Organization.name == name))
    ).scalar_one_or_none()
    if org is None:
        org = Organization(name=name)
        db.add(org)
        await db.commit()
        await db.refresh(org)
    return org


DEMO_TRUCKS = [
    {"name": "Alpha", "plate_number": "FW-001", "model": "Volvo FH16"},
    {"name": "Bravo", "plate_number": "FW-002", "model": "Scania R500"},
    {"name": "Charlie", "plate_number": "FW-003", "model": "Mercedes Actros"},
]


async def seed_admin(*, reset: bool) -> User:
    email = os.environ.get("SEED_ADMIN_EMAIL", "admin@example.com")
    password = os.environ.get("SEED_ADMIN_PASSWORD", "password123")
    role_name = os.environ.get("SEED_ADMIN_ROLE", "admin")

    try:
        role = UserRole(role_name)
    except ValueError:
        valid = ", ".join(r.value for r in UserRole)
        raise SystemExit(f"Invalid SEED_ADMIN_ROLE={role_name!r}. Valid: {valid}")

    async with SessionLocal() as db:
        org = await _get_or_create_org(db)
        existing = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()

        if existing and reset:
            await db.delete(existing)
            await db.commit()
            existing = None
            print(f"  deleted existing user {email}")

        if existing:
            print(f"✓ admin exists: {email} (role={existing.role.value}) — skipping")
            return existing

        user = User(org_id=org.id, email=email, password_hash=hash_password(password), role=role)
        db.add(user)
        await db.commit()
        await db.refresh(user)
        print(f"✓ created admin: {email} / {password} (role={role.value})")
        return user


async def seed_superadmin() -> None:
    """Create the platform operator's login, if configured.

    Both env vars must be set — no defaults on purpose. A superadmin can create,
    suspend and delete every customer company on the platform, so a well-known
    fallback password would be the single worst credential in the system.

    Never touches an existing account: if the email is already taken we print a
    notice and leave the row alone, so re-running the seeder can't silently reset
    the operator's password (or, worse, re-role an existing customer user).
    """
    email = os.environ.get("SEED_SUPERADMIN_EMAIL", "").strip()
    password = os.environ.get("SEED_SUPERADMIN_PASSWORD", "")

    if not email or not password:
        print("• SEED_SUPERADMIN_EMAIL/PASSWORD not set — skipping superadmin")
        return

    async with SessionLocal() as db:
        existing = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
        if existing:
            print(f"✓ superadmin exists: {email} (role={existing.role.value}) — leaving untouched")
            return

        org = await _get_or_create_org(db, "Platform")
        user = User(
            org_id=org.id,
            email=email,
            password_hash=hash_password(password),
            role=UserRole.superadmin,
        )
        db.add(user)
        await db.commit()
        print(f"✓ created superadmin: {email} (org={org.name})")


async def seed_trucks(org_id) -> None:
    async with SessionLocal() as db:
        created = 0
        for spec in DEMO_TRUCKS:
            existing = (
                await db.execute(select(Truck).where(Truck.plate_number == spec["plate_number"]))
            ).scalar_one_or_none()
            if existing:
                continue
            db.add(Truck(org_id=org_id, **spec))
            created += 1
        await db.commit()
        if created:
            print(f"✓ created {created} demo truck(s)")
        else:
            print("✓ demo trucks already present — skipping")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--admin-only", action="store_true", help="skip demo trucks")
    parser.add_argument(
        "--superadmin-only",
        action="store_true",
        help="create ONLY the platform superadmin — no demo admin, no demo trucks (use this on production)",
    )
    parser.add_argument("--reset", action="store_true", help="delete existing admin before recreating")
    args = parser.parse_args()

    print("Seeding database…")

    # --superadmin-only exists because the demo admin is a genuine hazard on a
    # live box: without it, `python seed.py` silently creates
    # admin@example.com / password123 as a full admin inside the first real
    # customer organization, plus demo trucks in their fleet. That is exactly
    # what happened once on production. Bootstrapping the platform operator
    # must not drag demo fixtures along with it.
    if args.superadmin_only:
        await seed_superadmin()
        print("Done.")
        return

    admin = await seed_admin(reset=args.reset)
    await seed_superadmin()
    if not args.admin_only:
        await seed_trucks(admin.org_id)
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
