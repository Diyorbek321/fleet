"""Test fixtures.

Loading order matters: env vars MUST be set before any `app.*` module is
imported, because `settings` is a module-level singleton. This file is
imported by pytest before tests — set secrets here, not in a fixture body.

The test database is built by **running the Alembic migrations**, not by
``Base.metadata.create_all``. That distinction is the whole point: with
``create_all`` the schema is derived from the models, so a model column that
no migration ever creates is structurally invisible to the entire suite — the
tests pass while production raises ``UndefinedColumnError`` on every SELECT.
Migrating the test database means model-vs-migration drift now fails the suite
instead of the customer (see ``tests/test_schema_drift.py`` for the assertion).

Consequence: the suite requires a real PostgreSQL server, because the
migrations use Postgres-only DDL (``ALTER TABLE ... ADD CONSTRAINT``, native
ENUM types) that SQLite cannot execute. Point ``TEST_DATABASE_URL`` at any
Postgres instance; the default matches the docker-compose dev database on host
port 5434. The named database is dropped and recreated on every run, so never
point it at a database whose contents matter.
"""
from __future__ import annotations

import asyncio
import os
import pathlib

# --- environment (must happen before importing app.*) ---
#
# A dedicated database, separate from the dev one, so a test run can never
# destroy the developer's seeded data.
_DEFAULT_TEST_DSN = "postgresql+asyncpg://fleet:fleet@localhost:5434/fleet_test"
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", _DEFAULT_TEST_DSN)

# Assigned, not setdefault: an inherited DATABASE_URL (a shell that sourced
# backend/.env, for instance) would otherwise point the suite at the dev
# database — which pytest_sessionstart would then drop.
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-not-for-production-use-only")
os.environ.setdefault("CORS_ORIGINS", "http://localhost:8080")
os.environ.setdefault("GPS_API_KEYS", "legacy-test-key")
os.environ.setdefault("ENV", "test")
os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("USE_REDIS_REFRESH_TOKENS", "false")
# Public sign-up is OFF in production (companies are provisioned by the platform
# operator), but the suite's `admin_token` fixture and tests/test_tenancy.py build
# their tenants through POST /api/auth/register — the cheapest way to get two
# genuinely separate orgs. Enabling it for the session keeps those tests honest
# about tenancy instead of coupling them to the superadmin console. The gate
# itself is covered explicitly in test_auth.py, which flips
# `settings.allow_public_registration` per-test with monkeypatch.
os.environ.setdefault("ALLOW_PUBLIC_REGISTRATION", "true")

import asyncpg  # noqa: E402
import pytest_asyncio  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from asgi_lifespan import LifespanManager  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.engine import URL, make_url  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker  # noqa: E402

from app.core.database import Base, SessionLocal, engine as app_engine, get_db  # noqa: E402
from app.core.rate_limit import limiter  # noqa: E402
from app.main import app  # noqa: E402


BACKEND_DIR = pathlib.Path(__file__).resolve().parent.parent


# --- test database lifecycle ------------------------------------------------
#
# Driven from pytest's session hooks rather than from a fixture because
# Alembic's env.py runs the async engine via ``asyncio.run()``, which raises
# if a loop is already running. Session hooks execute outside pytest-asyncio's
# loop, so ``asyncio.run()`` is safe there; an async fixture would not be.


async def _maintenance_connection(url: URL) -> asyncpg.Connection:
    """Connect to the server's ``postgres`` database.

    CREATE/DROP DATABASE cannot run from inside the database being altered, so
    every lifecycle statement needs this side connection.
    """
    return await asyncpg.connect(
        user=url.username,
        password=url.password,
        host=url.host,
        port=url.port,
        database="postgres",
    )


async def _recreate_database(url: URL) -> None:
    """DROP + CREATE the test database.

    ``WITH (FORCE)`` terminates leftover backends from a previously crashed
    run; without it a single stale connection makes DROP DATABASE block until
    it is killed by hand.
    """
    conn = await _maintenance_connection(url)
    try:
        await conn.execute(f'DROP DATABASE IF EXISTS "{url.database}" WITH (FORCE)')
        await conn.execute(f'CREATE DATABASE "{url.database}"')
    finally:
        await conn.close()


async def _drop_database(url: URL) -> None:
    conn = await _maintenance_connection(url)
    try:
        await conn.execute(f'DROP DATABASE IF EXISTS "{url.database}" WITH (FORCE)')
    finally:
        await conn.close()


def _alembic_config() -> Config:
    """Alembic config pointed at backend/alembic and the test DSN.

    ``script_location`` is absolutised so the suite runs from any cwd, and
    ``sqlalchemy.url`` is set explicitly so a migration can never be applied to
    the dev or production database even if DATABASE_URL says otherwise.
    """
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    return cfg


def pytest_sessionstart(session) -> None:
    """Create the test database and bring it to Alembic head."""
    url = make_url(TEST_DATABASE_URL)
    if url.get_backend_name() != "postgresql":
        raise RuntimeError(
            "The suite builds its schema with Alembic, whose migrations require "
            f"PostgreSQL. TEST_DATABASE_URL resolved to {url.get_backend_name()!r}."
        )
    asyncio.run(_recreate_database(url))
    command.upgrade(_alembic_config(), "head")


def pytest_sessionfinish(session, exitstatus) -> None:
    """Dispose the app engine, then drop the test database."""
    asyncio.run(app_engine.dispose())
    asyncio.run(_drop_database(make_url(TEST_DATABASE_URL)))


@pytest_asyncio.fixture(autouse=True)
async def _db_schema():
    """Empty every table before each test.

    The schema is migrated once per session (see ``pytest_sessionstart``);
    replaying the whole migration chain per test would add seconds to every
    single one. ``TRUNCATE ... CASCADE`` gives the same isolation the old
    drop_all/create_all pair gave, at a fraction of the cost.
    ``alembic_version`` is not in ``Base.metadata`` and so is left alone —
    the session must stay at head.
    """
    tables = ", ".join(f'"{name}"' for name in Base.metadata.tables)
    async with app_engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    yield


@pytest_asyncio.fixture(autouse=True)
async def _disable_rate_limits():
    """Rate-limiter state leaks across tests; disable it for the suite."""
    original = limiter.enabled
    limiter.enabled = False
    try:
        yield
    finally:
        limiter.enabled = original


@pytest_asyncio.fixture
async def db() -> AsyncSession:
    """A session on the test database, for rows the HTTP API cannot create.

    Raw GPS history at controlled timestamps is the motivating case: the ingest
    endpoint always stamps "now", so backdating a track — which every retention
    and analytics-window test needs — has to go through the ORM directly.
    """
    async with SessionLocal() as session:
        yield session


@pytest_asyncio.fixture
async def client():
    """FastAPI test client with full ASGI lifespan (so refresh_store etc. init)."""
    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as c:
            yield c


# --- user/token helpers ---


@pytest_asyncio.fixture
async def admin_token(client: AsyncClient) -> str:
    """Register a fresh org + its admin, return the admin's access token."""
    await client.post(
        "/api/auth/register",
        json={"email": "admin@test.com", "password": "password123", "org_name": "Test Org"},
    )
    res = await client.post(
        "/api/auth/login",
        json={"email": "admin@test.com", "password": "password123"},
    )
    assert res.status_code == 200, res.text
    return res.json()["access_token"]


@pytest_asyncio.fixture
async def operator_token(client: AsyncClient, admin_headers) -> str:
    """An operator created by the admin, inside the SAME organization."""
    res = await client.post(
        "/api/auth/users",
        headers=admin_headers,
        json={"email": "op@test.com", "password": "password123", "role": "operator"},
    )
    assert res.status_code == 201, res.text
    login = await client.post(
        "/api/auth/login",
        json={"email": "op@test.com", "password": "password123"},
    )
    return login.json()["access_token"]


@pytest_asyncio.fixture
async def admin_headers(admin_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {admin_token}"}


@pytest_asyncio.fixture
async def operator_headers(operator_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {operator_token}"}


@pytest_asyncio.fixture
async def driver_login(client: AsyncClient, admin_headers) -> dict:
    """Create a driver + a mobile login for them. Returns ids + auth headers."""
    driver = (
        await client.post(
            "/api/drivers",
            headers=admin_headers,
            json={"name": "Bob Driver", "license_number": "LIC-100"},
        )
    ).json()
    res = await client.post(
        f"/api/drivers/{driver['id']}/create-login",
        headers=admin_headers,
        json={"email": "bob@driver.com", "password": "driverpass123"},
    )
    assert res.status_code == 201, res.text
    login = (
        await client.post(
            "/api/auth/login",
            json={"email": "bob@driver.com", "password": "driverpass123"},
        )
    ).json()
    return {
        "driver_id": driver["id"],
        "headers": {"Authorization": f"Bearer {login['access_token']}"},
    }
