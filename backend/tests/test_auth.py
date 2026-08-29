"""Auth flow: register (org sign-up), login, /me, refresh rotation, logout, RBAC.

Public registration is off in production and enabled for the whole test session in
``conftest.py`` (the ``admin_token`` fixture and ``test_tenancy.py`` build their
tenants through it). The gate itself is therefore exercised here by flipping
``settings.allow_public_registration`` per test with monkeypatch — the router reads
the setting on every call, so the flip takes effect without re-importing anything.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.core.config import settings


@pytest.fixture
def public_registration_disabled(monkeypatch):
    """Restore FleetWatch's production posture: sign-up closed."""
    monkeypatch.setattr(settings, "allow_public_registration", False)


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


async def test_register_is_403_when_public_signup_is_disabled(
    client: AsyncClient, public_registration_disabled
):
    """The default posture: tenants are provisioned by the platform operator.

    An open sign-up on a paid product would let anyone mint a tenant, so the gate
    is checked before anything is written — no half-created org is left behind.
    """
    res = await client.post(
        "/api/auth/register",
        json={"email": "walkin@test.com", "password": "password123", "org_name": "Walk In"},
    )
    assert res.status_code == 403, res.text
    assert res.json()["detail"] == "Public registration is disabled"

    # Nothing was created, so the credentials do not authenticate either.
    login = await client.post(
        "/api/auth/login", json={"email": "walkin@test.com", "password": "password123"}
    )
    assert login.status_code == 401, "the rejected sign-up must not have created a user"


async def test_register_works_when_public_signup_is_enabled(client: AsyncClient, monkeypatch):
    monkeypatch.setattr(settings, "allow_public_registration", True)
    res = await client.post(
        "/api/auth/register",
        json={"email": "demo@test.com", "password": "password123", "org_name": "Demo Org"},
    )
    assert res.status_code == 201, res.text
    assert res.json()["role"] == "admin"


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


async def test_admin_can_create_a_second_admin(client: AsyncClient, admin_headers):
    """A company may have more than one owner.

    This used to be refused, which made us the only way to recover a company whose
    single admin was locked out — support work that a customer can do themselves.
    """
    res = await client.post(
        "/api/auth/users",
        headers=admin_headers,
        json={"email": "anotheradmin@test.com", "password": "password123", "role": "admin"},
    )
    assert res.status_code == 201, res.text
    assert res.json()["role"] == "admin"


async def test_create_user_rejects_superadmin_and_driver_roles(client: AsyncClient, admin_headers):
    """``superadmin`` would be escalation out of the tenant; ``driver`` must be
    created via /api/drivers so the login is linked to a Driver profile."""
    for role in ("superadmin", "driver"):
        res = await client.post(
            "/api/auth/users",
            headers=admin_headers,
            json={"email": f"{role}@test.com", "password": "password123", "role": role},
        )
        assert res.status_code == 400, f"role={role} must be refused, got {res.status_code}"


async def test_create_user_requires_admin(client: AsyncClient, operator_headers):
    res = await client.post(
        "/api/auth/users",
        headers=operator_headers,
        json={"email": "x@test.com", "password": "password123", "role": "operator"},
    )
    assert res.status_code == 403


# --- org-scoped user management (a company's own admin) ---------------------


async def _other_org_admin(client: AsyncClient) -> dict:
    """A second, unrelated company. Returns its admin's id + auth headers."""
    reg = await client.post(
        "/api/auth/register",
        json={"email": "other@rival.com", "password": "password123", "org_name": "Rival Fleet"},
    )
    assert reg.status_code == 201, reg.text
    login = await client.post(
        "/api/auth/login", json={"email": "other@rival.com", "password": "password123"}
    )
    return {
        "user_id": reg.json()["id"],
        "headers": {"Authorization": f"Bearer {login.json()['access_token']}"},
    }


async def test_list_users_returns_only_the_callers_org(
    client: AsyncClient, admin_headers, operator_headers
):
    await _other_org_admin(client)

    res = await client.get("/api/auth/users", headers=admin_headers)
    assert res.status_code == 200, res.text
    emails = {u["email"] for u in res.json()}
    assert emails == {"admin@test.com", "op@test.com"}, f"leaked or missing users: {emails}"


async def test_list_users_requires_admin(client: AsyncClient, operator_headers):
    assert (await client.get("/api/auth/users", headers=operator_headers)).status_code == 403


async def test_admin_updates_a_colleagues_role_and_password(
    client: AsyncClient, admin_headers, operator_headers
):
    users = (await client.get("/api/auth/users", headers=admin_headers)).json()
    op_id = next(u["id"] for u in users if u["email"] == "op@test.com")

    res = await client.patch(
        f"/api/auth/users/{op_id}",
        headers=admin_headers,
        json={"role": "manager", "password": "newpassword123"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["role"] == "manager"

    # The password really was reset — the old one no longer works.
    assert (
        await client.post("/api/auth/login", json={"email": "op@test.com", "password": "password123"})
    ).status_code == 401
    assert (
        await client.post(
            "/api/auth/login", json={"email": "op@test.com", "password": "newpassword123"}
        )
    ).status_code == 200


async def test_admin_cannot_promote_a_colleague_to_superadmin(
    client: AsyncClient, admin_headers, operator_headers
):
    users = (await client.get("/api/auth/users", headers=admin_headers)).json()
    op_id = next(u["id"] for u in users if u["email"] == "op@test.com")

    res = await client.patch(
        f"/api/auth/users/{op_id}", headers=admin_headers, json={"role": "superadmin"}
    )
    assert res.status_code == 400, res.text

    check = await client.get("/api/auth/users", headers=admin_headers)
    assert next(u for u in check.json() if u["id"] == op_id)["role"] == "operator"


async def test_admin_cannot_change_a_drivers_role(client: AsyncClient, admin_headers, driver_login):
    users = (await client.get("/api/auth/users", headers=admin_headers)).json()
    driver_user_id = next(u["id"] for u in users if u["email"] == "bob@driver.com")

    res = await client.patch(
        f"/api/auth/users/{driver_user_id}", headers=admin_headers, json={"role": "operator"}
    )
    assert res.status_code == 400, res.text


async def test_admin_cannot_demote_or_delete_themselves(client: AsyncClient, admin_headers):
    me = (await client.get("/api/auth/me", headers=admin_headers)).json()

    demote = await client.patch(
        f"/api/auth/users/{me['id']}", headers=admin_headers, json={"role": "operator"}
    )
    assert demote.status_code == 400, "demoting yourself can leave an org with no admin"

    delete = await client.delete(f"/api/auth/users/{me['id']}", headers=admin_headers)
    assert delete.status_code == 400, delete.text

    # Still an admin, still there.
    assert (await client.get("/api/auth/me", headers=admin_headers)).json()["role"] == "admin"


async def test_admin_deletes_a_colleague(client: AsyncClient, admin_headers, operator_headers):
    users = (await client.get("/api/auth/users", headers=admin_headers)).json()
    op_id = next(u["id"] for u in users if u["email"] == "op@test.com")

    res = await client.delete(f"/api/auth/users/{op_id}", headers=admin_headers)
    assert res.status_code == 204, res.text

    remaining = (await client.get("/api/auth/users", headers=admin_headers)).json()
    assert all(u["id"] != op_id for u in remaining)
    assert (
        await client.post("/api/auth/login", json={"email": "op@test.com", "password": "password123"})
    ).status_code == 401


async def test_cross_org_user_management_is_404(client: AsyncClient, admin_headers):
    """404 rather than 403 — a 403 would confirm the id exists on the platform."""
    other = await _other_org_admin(client)

    patched = await client.patch(
        f"/api/auth/users/{other['user_id']}", headers=admin_headers, json={"role": "operator"}
    )
    assert patched.status_code == 404, patched.text

    deleted = await client.delete(f"/api/auth/users/{other['user_id']}", headers=admin_headers)
    assert deleted.status_code == 404, deleted.text

    # The rival's admin is untouched and can still work.
    assert (await client.get("/api/auth/me", headers=other["headers"])).json()["role"] == "admin"


async def test_update_and_delete_user_require_admin(client: AsyncClient, admin_headers, operator_headers):
    me = (await client.get("/api/auth/me", headers=admin_headers)).json()
    assert (
        await client.patch(
            f"/api/auth/users/{me['id']}", headers=operator_headers, json={"password": "password1234"}
        )
    ).status_code == 403
    assert (
        await client.delete(f"/api/auth/users/{me['id']}", headers=operator_headers)
    ).status_code == 403


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
