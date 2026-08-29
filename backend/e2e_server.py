"""Start a throwaway backend for the end-to-end suite.

The E2E tests drive the real UI against the real API, so they need a real
database — but never the dev or production one. This recreates a dedicated
database from the migration chain, seeds exactly one organization with one
admin, and then runs uvicorn.

Rebuilding from migrations rather than from the models is the same choice
``tests/conftest.py`` makes and for the same reason: a model column no
migration creates is invisible to a schema derived from the models, and the E2E
run would pass against a database production will never have.

    python e2e_server.py                 # serve on :8001
    E2E_PORT=9000 python e2e_server.py

Environment:
    E2E_DATABASE_URL  target database (default: …/fleet_e2e on the dev server)
    E2E_EMAIL         seeded admin's email    (default: e2e@fleetwatch-e2e.com)
    E2E_PASSWORD      seeded admin's password (default: e2e-password-123)
    E2E_PORT          port to serve on        (default: 8001)
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

DATABASE_URL = os.environ.setdefault(
    "E2E_DATABASE_URL", "postgresql+asyncpg://fleet:fleet@localhost:5434/fleet_e2e"
)
# Not a .test or .example domain: pydantic's EmailStr rejects reserved TLDs,
# so the tidier-looking address fails validation at the login endpoint.
EMAIL = os.environ.setdefault("E2E_EMAIL", "e2e@fleetwatch-e2e.com")
PASSWORD = os.environ.setdefault("E2E_PASSWORD", "e2e-password-123")
PORT = int(os.environ.setdefault("E2E_PORT", "8001"))

# Must be set before any `app.*` import: settings is a module-level singleton.
os.environ["DATABASE_URL"] = DATABASE_URL
os.environ.setdefault("JWT_SECRET_KEY", "e2e-secret-key-at-least-32-characters-long")
# Both spellings of the loopback address: the browser treats http://localhost
# and http://127.0.0.1 as different origins, and Playwright drives the app on
# 127.0.0.1 while a developer opening the same port by hand usually types
# localhost. Listing one of them fails CORS for the other, and the only visible
# symptom is a login that silently never completes.
os.environ.setdefault(
    "CORS_ORIGINS",
    "http://127.0.0.1:4173,http://localhost:4173,http://127.0.0.1:5173,http://localhost:5173",
)
os.environ.setdefault("ENV", "test")
# The background scheduler would poll an external border-queue registry and fire
# Telegram jobs against a database the suite is actively resetting.
os.environ.setdefault("SCHEDULER_ENABLED", "false")

import asyncpg  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy.engine import URL, make_url  # noqa: E402


def _guard(url: URL) -> None:
    """Refuse to run against anything that is not obviously a scratch database.

    This script's first act is DROP DATABASE. The name check is cheap and the
    mistake it prevents — pointing E2E_DATABASE_URL at the dev or production
    DSN and losing everything — is not recoverable.
    """
    if url.get_backend_name() != "postgresql":
        raise SystemExit(f"E2E needs PostgreSQL, got {url.get_backend_name()!r}")
    if not (url.database or "").endswith("_e2e"):
        raise SystemExit(
            f"refusing to drop database {url.database!r}: the E2E database name "
            "must end in '_e2e'"
        )


async def _recreate(url: URL) -> None:
    dsn = URL.create(
        "postgresql",
        username=url.username,
        password=url.password,
        host=url.host,
        port=url.port,
        database="postgres",
    ).render_as_string(hide_password=False)
    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute(f'DROP DATABASE IF EXISTS "{url.database}" WITH (FORCE)')
        await conn.execute(f'CREATE DATABASE "{url.database}"')
    finally:
        await conn.close()


def _migrate() -> None:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", DATABASE_URL)
    command.upgrade(cfg, "head")


async def _seed() -> None:
    from app.core.database import SessionLocal
    from app.core.security import hash_password
    from app.models.enums import UserRole
    from app.models.organizations import Organization
    from app.models.users import User

    async with SessionLocal() as db:
        org = Organization(name="E2E Logistics")
        db.add(org)
        await db.flush()
        db.add(
            User(
                org_id=org.id,
                email=EMAIL,
                password_hash=hash_password(PASSWORD),
                role=UserRole.admin,
            )
        )
        await db.commit()


def main() -> None:
    url = make_url(DATABASE_URL)
    _guard(url)

    print(f"[e2e] recreating {url.database}", flush=True)
    asyncio.run(_recreate(url))
    print("[e2e] migrating", flush=True)
    _migrate()
    print(f"[e2e] seeding admin {EMAIL}", flush=True)
    asyncio.run(_seed())

    import uvicorn

    print(f"[e2e] serving on :{PORT}", flush=True)
    uvicorn.run("app.main:app", host="127.0.0.1", port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
