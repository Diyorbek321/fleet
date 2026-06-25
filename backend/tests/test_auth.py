"""Auth flow: register (org sign-up), login, /me, refresh rotation, logout, RBAC."""
from __future__ import annotations

from httpx import AsyncClient


async def test_register_creates_org_admin(client: AsyncClient):
    res = await client.post(
        "/api/auth/register",
        json={"email": "new@test.com", "password": "password123", "org_name": "Acme Fleet"},
    )
    assert res.status_code == 201
    body = res.json()
    assert body["email"] == "new@test.com"
    assert body["role"] == "admin"  # first user of a new org is always admin
    assert "id" in body
    assert "org_id" in body
    assert "password_hash" not in body


async def test_register_ignores_client_supplied_role(client: AsyncClient):
    # Privilege-escalation guard: a caller cannot self-assign a role.
    res = await client.post(
        "/api/auth/register",
        json={"email": "sneaky@test.com", "password": "password123", "org_name": "X", "role": "operator"},
    )
    assert res.status_code == 201
    assert res.json()["role"] == "admin"


async def test_register_requires_org_name(client: AsyncClient):
    res = await client.post(
        "/api/auth/register",
        json={"email": "noorg@test.com", "password": "password123"},
    )
    assert res.status_code == 422


async def test_register_duplicate_email_rejected(client: AsyncClient):
    payload = {"email": "dup@test.com", "password": "password123", "org_name": "Dup Org"}
    await client.post("/api/auth/register", json=payload)
    res = await client.post("/api/auth/register", json=payload)
    assert res.status_code == 400
    assert "already" in res.json()["detail"].lower()


async def test_register_weak_password_rejected(client: AsyncClient):
    res = await client.post(
        "/api/auth/register",
        json={"email": "weak@test.com", "password": "short", "org_name": "Weak Org"},
    )
    assert res.status_code == 422  # pydantic min_length=8


async def test_login_returns_tokens(client: AsyncClient):
    await client.post(
        "/api/auth/register",
        json={"email": "u@test.com", "password": "password123", "org_name": "U Org"},
    )
    res = await client.post(
        "/api/auth/login",
        json={"email": "u@test.com", "password": "password123"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["token_type"] == "bearer"


async def test_login_wrong_password_returns_401(client: AsyncClient):
    await client.post(
        "/api/auth/register",
        json={"email": "u@test.com", "password": "password123", "org_name": "U Org"},
    )
    res = await client.post(
        "/api/auth/login",
        json={"email": "u@test.com", "password": "wrongpassword"},
    )
    assert res.status_code == 401


async def test_login_unknown_email_returns_401(client: AsyncClient):
    res = await client.post(
        "/api/auth/login",
        json={"email": "nobody@test.com", "password": "password123"},
    )
    assert res.status_code == 401


async def test_me_requires_auth(client: AsyncClient):
    res = await client.get("/api/auth/me")
    assert res.status_code == 401


async def test_me_returns_current_user(client: AsyncClient, admin_headers):
    res = await client.get("/api/auth/me", headers=admin_headers)
    assert res.status_code == 200
    assert res.json()["email"] == "admin@test.com"
    assert res.json()["role"] == "admin"


async def test_admin_can_create_operator(client: AsyncClient, admin_headers):
    res = await client.post(
        "/api/auth/users",
        headers=admin_headers,
        json={"email": "newop@test.com", "password": "password123", "role": "operator"},
    )
    assert res.status_code == 201, res.text
    assert res.json()["role"] == "operator"


async def test_create_user_rejects_admin_role(client: AsyncClient, admin_headers):
    res = await client.post(
        "/api/auth/users",
        headers=admin_headers,
        json={"email": "anotheradmin@test.com", "password": "password123", "role": "admin"},
    )
    assert res.status_code == 400


async def test_create_user_requires_admin(client: AsyncClient, operator_headers):
    res = await client.post(
        "/api/auth/users",
        headers=operator_headers,
        json={"email": "x@test.com", "password": "password123", "role": "operator"},
    )
    assert res.status_code == 403


async def test_refresh_rotates_token(client: AsyncClient):
    await client.post(
        "/api/auth/register",
        json={"email": "r@test.com", "password": "password123", "org_name": "R Org"},
    )
    login = await client.post(
        "/api/auth/login",
        json={"email": "r@test.com", "password": "password123"},
    )
    refresh = login.json()["refresh_token"]

    res = await client.post("/api/auth/refresh", json={"refresh_token": refresh})
    assert res.status_code == 200
    new_refresh = res.json()["refresh_token"]
    assert new_refresh != refresh  # rotated

    # Old refresh is revoked
    reuse = await client.post("/api/auth/refresh", json={"refresh_token": refresh})
    assert reuse.status_code == 401


async def test_refresh_invalid_token_returns_401(client: AsyncClient):
    res = await client.post("/api/auth/refresh", json={"refresh_token": "garbage"})
    assert res.status_code == 401


async def test_logout_revokes_refresh(client: AsyncClient):
    await client.post(
        "/api/auth/register",
        json={"email": "l@test.com", "password": "password123", "org_name": "L Org"},
    )
    login = await client.post(
        "/api/auth/login",
        json={"email": "l@test.com", "password": "password123"},
    )
    refresh = login.json()["refresh_token"]

    out = await client.post("/api/auth/logout", json={"refresh_token": refresh})
    assert out.status_code == 200

    reuse = await client.post("/api/auth/refresh", json={"refresh_token": refresh})
    assert reuse.status_code == 401
