"""Password changes, and the sessions they must end.

Resetting a password used to leave every token already issued working: the
refresh store is keyed by the token string, so nothing could enumerate "every
token belonging to this user". An admin resetting a compromised account's
password bought nothing — the attacker's refresh token stayed valid for the
full 90-day window.

These tests exist because that failure is invisible from the outside. The reset
returns 200, the new password works, and the old session keeps working too.
"""
from __future__ import annotations

from httpx import AsyncClient


async def _login(client: AsyncClient, email: str, password: str) -> dict:
    res = await client.post("/api/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return res.json()


async def _make_colleague(client: AsyncClient, admin_headers, email: str, password: str) -> str:
    res = await client.post(
        "/api/auth/users",
        headers=admin_headers,
        json={"email": email, "password": password, "role": "operator"},
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


class TestAdminResetEndsExistingSessions:
    async def test_access_token_stops_working(self, client: AsyncClient, admin_headers):
        user_id = await _make_colleague(client, admin_headers, "reset1@x.com", "oldpassword1")
        tokens = await _login(client, "reset1@x.com", "oldpassword1")
        stale = {"Authorization": f"Bearer {tokens['access_token']}"}

        assert (await client.get("/api/auth/me", headers=stale)).status_code == 200

        res = await client.patch(
            f"/api/auth/users/{user_id}", headers=admin_headers,
            json={"password": "brandnewpass1"},
        )
        assert res.status_code == 200, res.text

        assert (await client.get("/api/auth/me", headers=stale)).status_code == 401

    async def test_refresh_token_stops_working(self, client: AsyncClient, admin_headers):
        """The one that matters: a refresh token lives 90 days by default."""
        user_id = await _make_colleague(client, admin_headers, "reset2@x.com", "oldpassword1")
        tokens = await _login(client, "reset2@x.com", "oldpassword1")

        await client.patch(
            f"/api/auth/users/{user_id}", headers=admin_headers,
            json={"password": "brandnewpass1"},
        )

        res = await client.post(
            "/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
        )
        assert res.status_code == 401

    async def test_the_new_password_works(self, client: AsyncClient, admin_headers):
        user_id = await _make_colleague(client, admin_headers, "reset3@x.com", "oldpassword1")
        await client.patch(
            f"/api/auth/users/{user_id}", headers=admin_headers,
            json={"password": "brandnewpass1"},
        )
        fresh = await _login(client, "reset3@x.com", "brandnewpass1")
        assert (
            await client.get(
                "/api/auth/me",
                headers={"Authorization": f"Bearer {fresh['access_token']}"},
            )
        ).status_code == 200

    async def test_a_role_change_alone_leaves_sessions_alone(
        self, client: AsyncClient, admin_headers
    ):
        """Only a password change ends sessions. A promotion is not a security event."""
        user_id = await _make_colleague(client, admin_headers, "reset4@x.com", "oldpassword1")
        tokens = await _login(client, "reset4@x.com", "oldpassword1")
        headers = {"Authorization": f"Bearer {tokens['access_token']}"}

        await client.patch(
            f"/api/auth/users/{user_id}", headers=admin_headers, json={"role": "manager"}
        )
        assert (await client.get("/api/auth/me", headers=headers)).status_code == 200

    async def test_other_users_sessions_are_untouched(self, client: AsyncClient, admin_headers):
        await _make_colleague(client, admin_headers, "keep1@x.com", "oldpassword1")
        victim_id = await _make_colleague(client, admin_headers, "keep2@x.com", "oldpassword1")

        bystander = await _login(client, "keep1@x.com", "oldpassword1")
        bystander_headers = {"Authorization": f"Bearer {bystander['access_token']}"}

        await client.patch(
            f"/api/auth/users/{victim_id}", headers=admin_headers,
            json={"password": "brandnewpass1"},
        )
        assert (await client.get("/api/auth/me", headers=bystander_headers)).status_code == 200


class TestMustChangePassword:
    async def test_an_admin_set_password_is_flagged(self, client: AsyncClient, admin_headers):
        """An admin-set password is one the admin knows."""
        user_id = await _make_colleague(client, admin_headers, "flag1@x.com", "oldpassword1")
        await client.patch(
            f"/api/auth/users/{user_id}", headers=admin_headers,
            json={"password": "brandnewpass1"},
        )
        tokens = await _login(client, "flag1@x.com", "brandnewpass1")
        me = await client.get(
            "/api/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
        )
        assert me.json()["must_change_password"] is True

    async def test_choosing_your_own_password_clears_the_flag(
        self, client: AsyncClient, admin_headers
    ):
        user_id = await _make_colleague(client, admin_headers, "flag2@x.com", "oldpassword1")
        await client.patch(
            f"/api/auth/users/{user_id}", headers=admin_headers,
            json={"password": "interimpass1"},
        )
        tokens = await _login(client, "flag2@x.com", "interimpass1")
        headers = {"Authorization": f"Bearer {tokens['access_token']}"}

        res = await client.post(
            "/api/auth/change-password", headers=headers,
            json={"current_password": "interimpass1", "new_password": "mineonly12345"},
        )
        assert res.status_code == 200, res.text

        after = await _login(client, "flag2@x.com", "mineonly12345")
        me = await client.get(
            "/api/auth/me", headers={"Authorization": f"Bearer {after['access_token']}"}
        )
        assert me.json()["must_change_password"] is False

    async def test_a_fresh_account_is_not_flagged(self, client: AsyncClient, admin_headers):
        await _make_colleague(client, admin_headers, "flag3@x.com", "oldpassword1")
        tokens = await _login(client, "flag3@x.com", "oldpassword1")
        me = await client.get(
            "/api/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
        )
        assert me.json()["must_change_password"] is False


class TestSelfServiceChange:
    async def test_wrong_current_password_is_refused(self, client: AsyncClient, admin_headers):
        await _make_colleague(client, admin_headers, "self1@x.com", "oldpassword1")
        tokens = await _login(client, "self1@x.com", "oldpassword1")
        headers = {"Authorization": f"Bearer {tokens['access_token']}"}

        res = await client.post(
            "/api/auth/change-password", headers=headers,
            json={"current_password": "notmypassword", "new_password": "somethingnew1"},
        )
        assert res.status_code == 400

        # And the old password still works, i.e. nothing was changed.
        await _login(client, "self1@x.com", "oldpassword1")

    async def test_it_ends_other_sessions_but_not_this_one(
        self, client: AsyncClient, admin_headers
    ):
        """A driver changing their password on a stolen-phone hunch expects the
        thief signed out — but not to be signed out of the device in their hand.
        """
        await _make_colleague(client, admin_headers, "self2@x.com", "oldpassword1")
        other_device = await _login(client, "self2@x.com", "oldpassword1")
        this_device = await _login(client, "self2@x.com", "oldpassword1")

        res = await client.post(
            "/api/auth/change-password",
            headers={"Authorization": f"Bearer {this_device['access_token']}"},
            json={"current_password": "oldpassword1", "new_password": "replacement12"},
        )
        assert res.status_code == 200
        issued = res.json()

        assert (
            await client.get(
                "/api/auth/me",
                headers={"Authorization": f"Bearer {other_device['access_token']}"},
            )
        ).status_code == 401
        assert (
            await client.get(
                "/api/auth/me",
                headers={"Authorization": f"Bearer {issued['access_token']}"},
            )
        ).status_code == 200

    async def test_requires_authentication(self, client: AsyncClient):
        res = await client.post(
            "/api/auth/change-password",
            json={"current_password": "x", "new_password": "yyyyyyyy"},
        )
        assert res.status_code == 401
