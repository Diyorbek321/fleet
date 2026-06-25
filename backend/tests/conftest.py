"""Test fixtures.

Loading order matters: env vars MUST be set before any `app.*` module is
imported, because `settings` is a module-level singleton. This file is
imported by pytest before tests — set secrets here, not in a fixture body.
"""
from __future__ import annotations

import os
import pathlib
import tempfile

# --- environment (must happen before importing app.*) ---
_TMP_DB = pathlib.Path(tempfile.mkdtemp()) / "test.db"
os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{_TMP_DB}")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-not-for-production-use-only")
os.environ.setdefault("CORS_ORIGINS", "http://localhost:8080")
os.environ.setdefault("GPS_API_KEYS", "legacy-test-key")
os.environ.setdefault("ENV", "test")
os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("USE_REDIS_REFRESH_TOKENS", "false")

import pytest_asyncio  # noqa: E402
from asgi_lifespan import LifespanManager  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker  # noqa: E402

from app.core.database import Base, engine as app_engine, get_db  # noqa: E402
from app.core.rate_limit import limiter  # noqa: E402
from app.main import app  # noqa: E402


@pytest_asyncio.fixture(autouse=True)
async def _db_schema():
    """Recreate all tables per test — cheap on SQLite, keeps tests isolated."""
    async with app_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with app_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


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
