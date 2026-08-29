"""Support access, the platform overview, and the audit trail.

Support access is a deliberate hole in the tenant isolation boundary that the
rest of the API exists to hold, so most of what is tested here is the fence
around it: who may use it, what they may do through it, and whether the
customer could ever find out that it happened.
"""
from __future__ import annotations

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.database import engine as app_engine
from app.core.security import hash_password
from app.deps.auth import SUPPORT_ORG_HEADER
from app.models.enums import UserRole
from app.models.organizations import Organization
from app.models.users import User

SUPERADMIN_EMAIL = "ops@fleetwatch.uz"
SUPERADMIN_PASSWORD = "superpassword123"


async def _login(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    res = await client.post("/api/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest_asyncio.fixture
async def platform(client: AsyncClient) -> dict:
    """The operator: a superadmin in its own Platform org, inserted directly.

    No endpoint mints a superadmin, and adding one would be the escalation hole
    the role design avoids.
    """
    async with async_sessionmaker(app_engine, expire_on_commit=False)() as db:
        org = Organization(name="Platform")
        db.add(org)
        await db.flush()
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
    return {"org_id": org_id, "headers": await _login(client, SUPERADMIN_EMAIL, SUPERADMIN_PASSWORD)}


@pytest_asyncio.fixture
async def customer(client: AsyncClient, platform) -> dict:
    """One onboarded company with a truck of its own."""
    res = await client.post(
        "/api/organizations",
        headers=platform["headers"],
        json={
            "name": "Toshkent Logistika",
            "admin_email": "boss@toshlog.uz",
            "admin_password": "password123",
        },
    )
    assert res.status_code == 201, res.text
    org = res.json()
    admin = await _login(client, "boss@toshlog.uz", "password123")
    truck = await client.post(
        "/api/trucks", headers=admin, json={"name": "Yo'lbars 01", "plate_number": "01 A 111 AA"}
    )
    assert truck.status_code == 200, truck.text
    return {"org": org, "admin": admin, "truck": truck.json()}


def _support(headers: dict, org_id: str) -> dict:
    return {**headers, SUPPORT_ORG_HEADER: org_id}


class TestSupportAccess:
    async def test_an_operator_can_read_a_customers_fleet(
        self, client: AsyncClient, platform, customer
    ):
        """The point of the feature: answering "my screen is wrong" by looking."""
        res = await client.get(
            "/api/trucks", headers=_support(platform["headers"], customer["org"]["id"])
        )
        assert res.status_code == 200, res.text
        assert [t["id"] for t in res.json()] == [customer["truck"]["id"]]

    async def test_without_the_header_an_operator_still_sees_nothing(
        self, client: AsyncClient, platform, customer
    ):
        """The isolation default is unchanged: opting in has to be explicit."""
        res = await client.get("/api/trucks", headers=platform["headers"])
        assert res.status_code == 200
        assert res.json() == []

    async def test_support_access_is_read_only(self, client: AsyncClient, platform, customer):
        """Reading a customer's screen answers questions; writing into their
        tenant makes the operator the reason their numbers changed."""
        headers = _support(platform["headers"], customer["org"]["id"])

        created = await client.post(
            "/api/trucks", headers=headers, json={"name": "Ghost", "plate_number": "99 X 999 XX"}
        )
        assert created.status_code == 403
        assert "read-only" in created.json()["detail"].lower()

        deleted = await client.delete(f"/api/trucks/{customer['truck']['id']}", headers=headers)
        assert deleted.status_code == 403

        # And the customer's fleet is exactly as it was.
        theirs = await client.get("/api/trucks", headers=customer["admin"])
        assert len(theirs.json()) == 1

    async def test_a_tenant_user_cannot_use_the_header(
        self, client: AsyncClient, platform, customer
    ):
        """403, not "quietly serve your own data": a client sending this is
        either probing the boundary or believes it can cross it. Silence hides
        both."""
        res = await client.get(
            "/api/trucks", headers=_support(customer["admin"], platform["org_id"])
        )
        assert res.status_code == 403
        assert "platform operators" in res.json()["detail"].lower()

    async def test_an_unknown_organization_is_404(self, client: AsyncClient, platform):
        res = await client.get(
            "/api/trucks",
            headers=_support(platform["headers"], "00000000-0000-0000-0000-000000000000"),
        )
        assert res.status_code == 404

    async def test_a_malformed_organization_id_is_400(self, client: AsyncClient, platform):
        res = await client.get("/api/trucks", headers=_support(platform["headers"], "not-a-uuid"))
        assert res.status_code == 400

    async def test_anonymous_cannot_use_the_header(self, client: AsyncClient, customer):
        res = await client.get(
            "/api/trucks", headers={SUPPORT_ORG_HEADER: customer["org"]["id"]}
        )
        assert res.status_code == 401

    async def test_the_customers_money_screens_are_reachable(
        self, client: AsyncClient, platform, customer
    ):
        """The screens support is actually called about."""
        headers = _support(platform["headers"], customer["org"]["id"])
        for path in (
            "/api/reports/fleet-summary",
            "/api/analytics/leakage-summary?days=30",
            "/api/reports/period?kind=month&offset=0",
        ):
            res = await client.get(path, headers=headers)
            assert res.status_code == 200, f"{path}: {res.status_code} {res.text}"


class TestSupportAccessIsRecorded:
    async def test_looking_at_a_customer_leaves_a_trace(
        self, client: AsyncClient, platform, customer
    ):
        """A customer who asks "who looked at my data" gets an answer."""
        await client.get(
            "/api/trucks", headers=_support(platform["headers"], customer["org"]["id"])
        )

        log = await client.get("/api/organizations/platform/audit", headers=platform["headers"])
        assert log.status_code == 200, log.text
        reads = [e for e in log.json() if e["action"] == "support.read"]
        assert len(reads) == 1
        assert reads[0]["target_org_id"] == customer["org"]["id"]
        assert reads[0]["actor_email"] == SUPERADMIN_EMAIL

    async def test_a_session_is_one_entry_not_one_per_request(
        self, client: AsyncClient, platform, customer
    ):
        """One screen fires half a dozen requests. A row each would bury the
        deliberate actions under near-identical noise."""
        headers = _support(platform["headers"], customer["org"]["id"])
        for path in ("/api/trucks", "/api/drivers", "/api/trips", "/api/geofences"):
            await client.get(path, headers=headers)

        log = await client.get("/api/organizations/platform/audit", headers=platform["headers"])
        reads = [e for e in log.json() if e["action"] == "support.read"]
        assert len(reads) == 1


class TestAuditTrail:
    async def test_onboarding_suspension_and_deletion_are_all_recorded(
        self, client: AsyncClient, platform
    ):
        created = await client.post(
            "/api/organizations",
            headers=platform["headers"],
            json={"name": "Audit Co", "admin_email": "a@audit.uz", "admin_password": "password123"},
        )
        org_id = created.json()["id"]

        await client.patch(
            f"/api/organizations/{org_id}", headers=platform["headers"], json={"is_active": False}
        )
        await client.patch(
            f"/api/organizations/{org_id}", headers=platform["headers"], json={"is_active": True}
        )
        await client.patch(
            f"/api/organizations/{org_id}",
            headers=platform["headers"],
            json={"contact_name": "Yangi kontakt"},
        )
        await client.delete(
            f"/api/organizations/{org_id}?confirm=Audit Co", headers=platform["headers"]
        )

        log = await client.get("/api/organizations/platform/audit", headers=platform["headers"])
        actions = [e["action"] for e in log.json()]
        for expected in (
            "organization.create",
            "organization.suspend",
            "organization.reactivate",
            "organization.update",
            "organization.delete",
        ):
            assert expected in actions, f"{expected} not recorded: {actions}"

    async def test_the_deletion_record_outlives_the_organization(
        self, client: AsyncClient, platform
    ):
        """The one event whose subject is guaranteed to be gone.

        target_org_id is deliberately not a foreign key, and the name is copied
        in — otherwise the row describing a deletion would be deleted by it.
        """
        created = await client.post(
            "/api/organizations",
            headers=platform["headers"],
            json={"name": "Gone Ltd", "admin_email": "g@gone.uz", "admin_password": "password123"},
        )
        org_id = created.json()["id"]
        await client.delete(
            f"/api/organizations/{org_id}?confirm=Gone Ltd", headers=platform["headers"]
        )

        log = await client.get("/api/organizations/platform/audit", headers=platform["headers"])
        deletion = next(e for e in log.json() if e["action"] == "organization.delete")
        assert deletion["target_org_name"] == "Gone Ltd"
        assert deletion["target_org_id"] == org_id

    async def test_the_log_can_be_filtered_to_one_customer(
        self, client: AsyncClient, platform
    ):
        first = await client.post(
            "/api/organizations", headers=platform["headers"],
            json={"name": "One", "admin_email": "1@x.uz", "admin_password": "password123"},
        )
        await client.post(
            "/api/organizations", headers=platform["headers"],
            json={"name": "Two", "admin_email": "2@x.uz", "admin_password": "password123"},
        )
        org_id = first.json()["id"]

        log = await client.get(
            f"/api/organizations/platform/audit?org_id={org_id}", headers=platform["headers"]
        )
        assert log.status_code == 200
        assert {e["target_org_id"] for e in log.json()} == {org_id}

    async def test_a_customer_admin_cannot_read_the_audit_log(
        self, client: AsyncClient, platform, customer
    ):
        res = await client.get(
            "/api/organizations/platform/audit", headers=customer["admin"]
        )
        assert res.status_code == 403

    async def test_there_is_no_way_to_edit_or_delete_an_event(self, client: AsyncClient, platform):
        """A log the subject can tidy afterwards answers nothing."""
        for method in ("POST", "PATCH", "PUT", "DELETE"):
            res = await client.request(
                method, "/api/organizations/platform/audit", headers=platform["headers"]
            )
            assert res.status_code in (404, 405), f"{method} is exposed: {res.status_code}"


class TestPlatformStats:
    async def test_it_counts_every_customer(self, client: AsyncClient, platform, customer):
        res = await client.get("/api/organizations/platform/stats", headers=platform["headers"])
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["organizations"] == 1
        assert body["active_organizations"] == 1
        assert body["suspended_organizations"] == 0
        assert body["trucks"] == 1

    async def test_the_platform_org_is_not_counted_as_a_customer(
        self, client: AsyncClient, platform
    ):
        """We are not our own customer; counting ourselves overstates the
        business by one on every screen this appears on."""
        res = await client.get("/api/organizations/platform/stats", headers=platform["headers"])
        assert res.json()["organizations"] == 0

    async def test_a_suspended_customer_is_split_out(self, client: AsyncClient, platform, customer):
        await client.patch(
            f"/api/organizations/{customer['org']['id']}",
            headers=platform["headers"],
            json={"is_active": False},
        )
        body = (
            await client.get("/api/organizations/platform/stats", headers=platform["headers"])
        ).json()
        assert body["organizations"] == 1
        assert body["active_organizations"] == 0
        assert body["suspended_organizations"] == 1

    async def test_a_customer_admin_is_refused(self, client: AsyncClient, platform, customer):
        res = await client.get(
            "/api/organizations/platform/stats", headers=customer["admin"]
        )
        assert res.status_code == 403
