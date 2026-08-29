"""Platform-operator console: /api/organizations.

The superadmin role cannot be minted over the API by design (see
``app/routers/organizations.py`` — ``_ASSIGNABLE_ROLES`` excludes it), so the
fixture below inserts the platform operator straight into the database, the same
way ``backend/seed.py`` does. Everything after that goes through HTTP, because the
point of these tests is the wire contract: who gets 401, who gets 403, and what a
superadmin can actually do to a customer company.

The other half of what is asserted here is what a superadmin deliberately *cannot*
do: they hold no cross-tenant powers outside this router, and suspending a company
must be reversible without touching its data.
"""
from __future__ import annotations

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.database import engine as app_engine
from app.core.security import hash_password
from app.models.enums import UserRole
from app.models.organizations import Organization
from app.models.users import User

SUPERADMIN_EMAIL = "platform@fleetwatch.uz"
SUPERADMIN_PASSWORD = "superpassword123"


async def _login(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    res = await client.post("/api/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest_asyncio.fixture
async def platform(client: AsyncClient) -> dict:
    """The platform operator: a superadmin in its own degenerate "Platform" org.

    Written directly to the database on purpose — no endpoint creates a superadmin,
    and adding one would be the escalation hole the whole role design avoids.
    """
    async with async_sessionmaker(app_engine, expire_on_commit=False)() as db:
        org = Organization(name="Platform")
        db.add(org)
        await db.flush()  # assigns org.id
        db.add(
            User(
                org_id=org.id,
                email=SUPERADMIN_EMAIL,
                password_hash=hash_password(SUPERADMIN_PASSWORD),
                role=UserRole.superadmin,
            )
        )
        await db.commit()
        org_id = str(org.id)

    headers = await _login(client, SUPERADMIN_EMAIL, SUPERADMIN_PASSWORD)
    return {"org_id": org_id, "headers": headers}


@pytest_asyncio.fixture
async def superadmin_headers(platform) -> dict[str, str]:
    return platform["headers"]


async def _create_org(client: AsyncClient, headers: dict, name: str, email: str) -> dict:
    res = await client.post(
        "/api/organizations",
        headers=headers,
        json={"name": name, "admin_email": email, "admin_password": "password123"},
    )
    assert res.status_code == 201, res.text
    return res.json()


# --- provisioning -----------------------------------------------------------


async def test_superadmin_onboards_company_and_its_admin_can_work(
    client: AsyncClient, superadmin_headers
):
    """The whole onboarding flow: one POST, and the customer can log in."""
    org = await _create_org(client, superadmin_headers, "Toshkent Logistika", "boss@toshlog.uz")
    assert org["is_active"] is True, "a newly onboarded company must not start suspended"
    assert org["user_count"] == 1, "the org is created with exactly its first admin"
    assert org["truck_count"] == 0 and org["trip_count"] == 0

    # The provisioned admin can log in and sees an empty fleet of their own.
    admin_headers = await _login(client, "boss@toshlog.uz", "password123")
    me = await client.get("/api/auth/me", headers=admin_headers)
    assert me.status_code == 200, me.text
    assert me.json()["role"] == "admin"
    assert me.json()["org_id"] == org["id"]

    trucks = await client.get("/api/trucks", headers=admin_headers)
    assert trucks.status_code == 200, trucks.text
    assert trucks.json() == [], "a brand-new company owns no trucks"


async def test_create_organization_rejects_duplicate_admin_email(
    client: AsyncClient, superadmin_headers, admin_headers
):
    # admin_headers already registered admin@test.com.
    res = await client.post(
        "/api/organizations",
        headers=superadmin_headers,
        json={"name": "Clone Co", "admin_email": "admin@test.com", "admin_password": "password123"},
    )
    assert res.status_code == 400, res.text

    # And the organization must not have been created either — a rolled-back
    # tenant is the reason org + admin share one transaction.
    listing = await client.get("/api/organizations?q=Clone", headers=superadmin_headers)
    assert listing.json() == [], "the org insert must roll back with the failed admin insert"


async def test_list_is_newest_first_and_searchable(client: AsyncClient, superadmin_headers):
    await _create_org(client, superadmin_headers, "Alpha Trans", "a@alpha.uz")
    await _create_org(client, superadmin_headers, "Beta Yuk", "b@beta.uz")

    res = await client.get("/api/organizations", headers=superadmin_headers)
    assert res.status_code == 200, res.text
    names = [o["name"] for o in res.json()]
    assert names[:2] == ["Beta Yuk", "Alpha Trans"], f"expected newest first, got {names}"

    hit = await client.get("/api/organizations?q=alph", headers=superadmin_headers)
    assert [o["name"] for o in hit.json()] == ["Alpha Trans"], "?q= is a case-insensitive search"


async def test_get_missing_organization_is_404(client: AsyncClient, superadmin_headers):
    missing = "00000000-0000-0000-0000-000000000000"
    res = await client.get(f"/api/organizations/{missing}", headers=superadmin_headers)
    assert res.status_code == 404, res.text


# --- authorization ----------------------------------------------------------


def _all_endpoints(org_id: str) -> list[tuple[str, str, dict | None]]:
    """Every route on the router, as (method, url, json body)."""
    return [
        ("GET", "/api/organizations", None),
        (
            "POST",
            "/api/organizations",
            {"name": "Sneaky Co", "admin_email": "s@sneaky.uz", "admin_password": "password123"},
        ),
        ("GET", f"/api/organizations/{org_id}", None),
        ("PATCH", f"/api/organizations/{org_id}", {"name": "Renamed"}),
        ("DELETE", f"/api/organizations/{org_id}?confirm=Victim Co", None),
        ("GET", f"/api/organizations/{org_id}/users", None),
        (
            "POST",
            f"/api/organizations/{org_id}/users",
            {"email": "x@sneaky.uz", "password": "password123", "role": "admin"},
        ),
    ]


async def test_company_admin_is_forbidden_everywhere(
    client: AsyncClient, superadmin_headers, admin_headers
):
    """A customer's own admin must never reach the platform console."""
    org = await _create_org(client, superadmin_headers, "Victim Co", "v@victim.uz")

    for method, url, body in _all_endpoints(org["id"]):
        res = await client.request(method, url, headers=admin_headers, json=body)
        assert res.status_code == 403, f"{method} {url} should be 403 for a company admin, got {res.status_code}"

    # Nothing leaked and nothing changed.
    still = await client.get(f"/api/organizations/{org['id']}", headers=superadmin_headers)
    assert still.json()["name"] == "Victim Co"


async def test_unauthenticated_is_401_everywhere(
    client: AsyncClient, superadmin_headers
):
    org = await _create_org(client, superadmin_headers, "Victim Co", "v@victim.uz")

    for method, url, body in _all_endpoints(org["id"]):
        res = await client.request(method, url, json=body)
        assert res.status_code == 401, f"{method} {url} should be 401 without a token, got {res.status_code}"


async def test_superadmin_gets_no_cross_tenant_fleet_data(
    client: AsyncClient, superadmin_headers, admin_headers
):
    """The role is scoped on purpose: it manages companies, not their trucks."""
    created = await client.post(
        "/api/trucks", headers=admin_headers, json={"name": "Customer Truck", "plate_number": "C-1"}
    )
    assert created.status_code == 200, created.text

    mine = await client.get("/api/trucks", headers=superadmin_headers)
    assert mine.status_code == 200, mine.text
    assert mine.json() == [], "a superadmin sees only its own (empty) Platform org's fleet"


# --- suspension -------------------------------------------------------------


async def test_suspension_blocks_the_customer_and_is_reversible(
    client: AsyncClient, superadmin_headers, platform
):
    org = await _create_org(client, superadmin_headers, "Unpaid Co", "boss@unpaid.uz")
    customer_headers = await _login(client, "boss@unpaid.uz", "password123")
    assert (await client.get("/api/trucks", headers=customer_headers)).status_code == 200

    suspended = await client.patch(
        f"/api/organizations/{org['id']}", headers=superadmin_headers, json={"is_active": False}
    )
    assert suspended.status_code == 200, suspended.text
    assert suspended.json()["is_active"] is False

    # The already-issued token stops working — is_active is re-read per request,
    # not baked into the JWT.
    blocked = await client.get("/api/trucks", headers=customer_headers)
    assert blocked.status_code == 403, blocked.text
    assert blocked.json()["detail"] == "Organization is suspended"

    # And they cannot log in again to get a fresh one.
    relogin = await client.post(
        "/api/auth/login", json={"email": "boss@unpaid.uz", "password": "password123"}
    )
    assert relogin.status_code == 403, relogin.text
    assert relogin.json()["detail"] == "Organization is suspended"

    # The platform operator is unaffected by a customer's suspension.
    assert (await client.get("/api/organizations", headers=superadmin_headers)).status_code == 200

    # Paying the invoice restores access with the original token — no data lost.
    restored = await client.patch(
        f"/api/organizations/{org['id']}", headers=superadmin_headers, json={"is_active": True}
    )
    assert restored.status_code == 200, restored.text
    assert (await client.get("/api/trucks", headers=customer_headers)).status_code == 200


async def test_suspending_the_platform_org_does_not_lock_the_operator_out(
    client: AsyncClient, superadmin_headers, platform
):
    """Superadmins are exempt from the suspension check.

    Without the exemption, one careless PATCH on the Platform org would make the
    endpoint needed to undo it unreachable.
    """
    res = await client.patch(
        f"/api/organizations/{platform['org_id']}",
        headers=superadmin_headers,
        json={"is_active": False},
    )
    assert res.status_code == 200, res.text

    assert (await client.get("/api/organizations", headers=superadmin_headers)).status_code == 200
    relogin = await client.post(
        "/api/auth/login", json={"email": SUPERADMIN_EMAIL, "password": SUPERADMIN_PASSWORD}
    )
    assert relogin.status_code == 200, relogin.text


async def test_patch_updates_contact_details(client: AsyncClient, superadmin_headers):
    org = await _create_org(client, superadmin_headers, "Contact Co", "c@contact.uz")
    res = await client.patch(
        f"/api/organizations/{org['id']}",
        headers=superadmin_headers,
        json={"contact_name": "Aziz", "contact_phone": "+998901234567", "notes": "pays quarterly"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["contact_name"] == "Aziz"
    assert body["contact_phone"] == "+998901234567"
    assert body["notes"] == "pays quarterly"
    assert body["name"] == "Contact Co", "an unsent field must be left alone"


# --- counts -----------------------------------------------------------------


async def test_counts_reflect_the_customers_fleet(client: AsyncClient, superadmin_headers):
    org = await _create_org(client, superadmin_headers, "Counted Co", "boss@counted.uz")
    customer_headers = await _login(client, "boss@counted.uz", "password123")

    truck = await client.post(
        "/api/trucks", headers=customer_headers, json={"name": "T1", "plate_number": "CNT-1"}
    )
    assert truck.status_code == 200, truck.text
    driver = await client.post(
        "/api/drivers", headers=customer_headers, json={"name": "D1", "license_number": "CNT-LIC-1"}
    )
    assert driver.status_code == 200, driver.text
    trip = await client.post(
        "/api/trips",
        headers=customer_headers,
        json={"truck_id": truck.json()["id"], "driver_id": driver.json()["id"], "rate": 1000000},
    )
    assert trip.status_code == 200, trip.text
    extra_user = await client.post(
        "/api/auth/users",
        headers=customer_headers,
        json={"email": "op@counted.uz", "password": "password123", "role": "operator"},
    )
    assert extra_user.status_code == 201, extra_user.text

    detail = await client.get(f"/api/organizations/{org['id']}", headers=superadmin_headers)
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["user_count"] == 2, f"admin + operator, got {body['user_count']}"
    assert body["truck_count"] == 1
    assert body["driver_count"] == 1
    assert body["trip_count"] == 1

    # The list endpoint computes the same numbers (correlated subqueries, one query).
    row = next(o for o in (await client.get("/api/organizations", headers=superadmin_headers)).json()
               if o["id"] == org["id"])
    assert (row["user_count"], row["truck_count"], row["driver_count"], row["trip_count"]) == (2, 1, 1, 1)


async def test_counts_do_not_bleed_between_organizations(client: AsyncClient, superadmin_headers):
    """The counts are correlated per row — a busy tenant must not inflate a quiet one."""
    busy = await _create_org(client, superadmin_headers, "Busy Co", "boss@busy.uz")
    quiet = await _create_org(client, superadmin_headers, "Quiet Co", "boss@quiet.uz")
    busy_headers = await _login(client, "boss@busy.uz", "password123")
    for plate in ("B-1", "B-2"):
        res = await client.post(
            "/api/trucks", headers=busy_headers, json={"name": plate, "plate_number": plate}
        )
        assert res.status_code == 200, res.text

    rows = {o["id"]: o for o in (await client.get("/api/organizations", headers=superadmin_headers)).json()}
    assert rows[busy["id"]]["truck_count"] == 2
    assert rows[quiet["id"]]["truck_count"] == 0


# --- org users --------------------------------------------------------------


async def test_superadmin_lists_and_adds_users_of_a_company(
    client: AsyncClient, superadmin_headers
):
    org = await _create_org(client, superadmin_headers, "Support Co", "boss@support.uz")

    created = await client.post(
        f"/api/organizations/{org['id']}/users",
        headers=superadmin_headers,
        json={"email": "rescue@support.uz", "password": "password123", "role": "admin"},
    )
    assert created.status_code == 201, created.text
    assert created.json()["role"] == "admin"
    assert created.json()["org_id"] == org["id"], "the user must land in the targeted org"

    users = await client.get(f"/api/organizations/{org['id']}/users", headers=superadmin_headers)
    assert users.status_code == 200, users.text
    assert {u["email"] for u in users.json()} == {"boss@support.uz", "rescue@support.uz"}

    # The rescue admin really can log in — the point of the recovery path.
    assert await _login(client, "rescue@support.uz", "password123")


async def test_superadmin_cannot_mint_a_superadmin_or_a_driver(
    client: AsyncClient, superadmin_headers
):
    org = await _create_org(client, superadmin_headers, "Roles Co", "boss@roles.uz")
    for role in ("superadmin", "driver"):
        res = await client.post(
            f"/api/organizations/{org['id']}/users",
            headers=superadmin_headers,
            json={"email": f"{role}@roles.uz", "password": "password123", "role": role},
        )
        assert res.status_code == 400, f"role={role} must be refused, got {res.status_code}"


# --- deletion ---------------------------------------------------------------


async def test_delete_requires_the_exact_name_and_is_a_no_op_otherwise(
    client: AsyncClient, superadmin_headers
):
    org = await _create_org(client, superadmin_headers, "Doomed Co", "boss@doomed.uz")
    url = f"/api/organizations/{org['id']}"

    # No confirmation at all.
    bare = await client.delete(url, headers=superadmin_headers)
    assert bare.status_code == 400, f"delete without ?confirm= must be refused, got {bare.status_code}"

    # Wrong confirmation.
    wrong = await client.delete(f"{url}?confirm=doomed+co", headers=superadmin_headers)
    assert wrong.status_code == 400, wrong.text

    # Still there after both refusals.
    assert (await client.get(url, headers=superadmin_headers)).status_code == 200

    ok = await client.delete(f"{url}?confirm=Doomed Co", headers=superadmin_headers)
    assert ok.status_code == 204, ok.text
    assert (await client.get(url, headers=superadmin_headers)).status_code == 404


async def test_delete_cascades_to_the_companys_users(client: AsyncClient, superadmin_headers):
    org = await _create_org(client, superadmin_headers, "Gone Co", "boss@gone.uz")
    customer_headers = await _login(client, "boss@gone.uz", "password123")
    truck = await client.post(
        "/api/trucks", headers=customer_headers, json={"name": "G1", "plate_number": "G-1"}
    )
    assert truck.status_code == 200, truck.text

    res = await client.delete(
        f"/api/organizations/{org['id']}?confirm=Gone Co", headers=superadmin_headers
    )
    assert res.status_code == 204, res.text

    # The admin no longer exists, so the credentials no longer authenticate.
    relogin = await client.post(
        "/api/auth/login", json={"email": "boss@gone.uz", "password": "password123"}
    )
    assert relogin.status_code == 401, relogin.text


async def test_cannot_delete_own_organization(client: AsyncClient, superadmin_headers, platform):
    """Refused even with a correct confirmation — it would delete the caller."""
    res = await client.delete(
        f"/api/organizations/{platform['org_id']}?confirm=Platform", headers=superadmin_headers
    )
    assert res.status_code == 400, res.text
    assert (
        await client.get(f"/api/organizations/{platform['org_id']}", headers=superadmin_headers)
    ).status_code == 200


async def test_delete_missing_organization_is_404(client: AsyncClient, superadmin_headers):
    missing = "00000000-0000-0000-0000-000000000000"
    res = await client.delete(f"/api/organizations/{missing}?confirm=whatever", headers=superadmin_headers)
    assert res.status_code == 404, res.text


# --- suspension reaches the non-HTTP surfaces too ---------------------------


async def test_suspended_company_cannot_refresh_its_way_back_in(
    client: AsyncClient, superadmin_headers, platform
):
    """A refresh token outlives an access token by weeks.

    If /api/auth/refresh only checked that the user still exists, a client that
    was signed in when its company got suspended would keep minting itself fresh
    access tokens for the whole 90-day refresh TTL — and each one is also a valid
    ticket into /ws. Suspension has to be enforced wherever tokens are issued.
    """
    org = await _create_org(client, superadmin_headers, "Lapsed Co", "boss@lapsed.uz")
    login = await client.post(
        "/api/auth/login", json={"email": "boss@lapsed.uz", "password": "password123"}
    )
    assert login.status_code == 200, login.text
    refresh = login.json()["refresh_token"]

    suspended = await client.patch(
        f"/api/organizations/{org['id']}", headers=superadmin_headers, json={"is_active": False}
    )
    assert suspended.status_code == 200, suspended.text

    blocked = await client.post("/api/auth/refresh", json={"refresh_token": refresh})
    assert blocked.status_code == 403, blocked.text
    assert blocked.json()["detail"] == "Organization is suspended"

    # Un-suspending restores it — the token was rejected, not consumed.
    await client.patch(
        f"/api/organizations/{org['id']}", headers=superadmin_headers, json={"is_active": True}
    )
    restored = await client.post("/api/auth/refresh", json={"refresh_token": refresh})
    assert restored.status_code == 200, restored.text


async def test_websocket_authorization_follows_suspension(
    client: AsyncClient, superadmin_headers, platform
):
    """The live map must go dark for a suspended tenant.

    ``/ws`` never passes through ``get_current_user`` — it authenticates the query
    string itself — so the suspension check has to be duplicated there. Asserted
    against the resolver rather than a real socket because the suite's async engine
    is bound to pytest-asyncio's loop and starlette's WebSocket test client runs its
    own.
    """
    from app.routers.ws import _authorized_org_id

    org = await _create_org(client, superadmin_headers, "Darkened Co", "boss@dark.uz")
    login = await client.post(
        "/api/auth/login", json={"email": "boss@dark.uz", "password": "password123"}
    )
    token = login.json()["access_token"]

    sessionmaker = async_sessionmaker(app_engine, expire_on_commit=False)

    async with sessionmaker() as db:
        assert str(await _authorized_org_id(db, token)) == org["id"]
        assert await _authorized_org_id(db, "not-a-jwt") is None

    suspended = await client.patch(
        f"/api/organizations/{org['id']}", headers=superadmin_headers, json={"is_active": False}
    )
    assert suspended.status_code == 200, suspended.text

    async with sessionmaker() as db:
        assert await _authorized_org_id(db, token) is None, (
            "a suspended tenant kept its live feed — every REST call 403s but the "
            "truck positions keep streaming"
        )


async def test_platform_org_admin_cannot_hijack_the_superadmin_account(
    client: AsyncClient, superadmin_headers, platform
):
    """A support engineer in the "Platform" org is still only an admin.

    ``POST /api/organizations/{id}/users`` deliberately allows adding an admin to
    any org, the operator's own included. Those org-scoped user endpoints filter on
    ``org_id`` alone, so without an explicit superadmin exclusion that colleague
    could PATCH a new password onto the platform operator's account and inherit
    every customer company on the platform.
    """
    added = await client.post(
        f"/api/organizations/{platform['org_id']}/users",
        headers=superadmin_headers,
        json={"email": "support@fleetwatch.uz", "password": "password123", "role": "admin"},
    )
    assert added.status_code == 201, added.text
    support_headers = await _login(client, "support@fleetwatch.uz", "password123")

    listed = await client.get("/api/auth/users", headers=support_headers)
    assert listed.status_code == 200, listed.text
    superadmin_id = next(
        u["id"] for u in listed.json() if u["email"] == SUPERADMIN_EMAIL
    )

    hijack = await client.patch(
        f"/api/auth/users/{superadmin_id}",
        headers=support_headers,
        json={"password": "iownyounow123"},
    )
    assert hijack.status_code == 404, hijack.text

    removed = await client.delete(
        f"/api/auth/users/{superadmin_id}", headers=support_headers
    )
    assert removed.status_code == 404, removed.text

    # The operator's original password still works and still reaches the console.
    still_ours = await _login(client, SUPERADMIN_EMAIL, SUPERADMIN_PASSWORD)
    assert (await client.get("/api/organizations", headers=still_ours)).status_code == 200
