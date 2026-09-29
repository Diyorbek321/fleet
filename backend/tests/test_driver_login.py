"""A driver signs in with a short login, not an email address.

Drivers were handed logins like ``10422TCA@gmail.com`` — a made-up mailbox
nobody reads, typed on a phone keyboard that capitalises the first letter on
its own. Half the "the app won't let me in" calls were exactly that. A login is
now whatever the dispatcher chooses (the plate is the usual pick), matched
without regard to case, and the dispatcher can reset it and the password from
the panel instead of having no way back once an account existed.
"""
from __future__ import annotations

from httpx import AsyncClient


async def _driver(client: AsyncClient, headers: dict, name: str = "Farhod") -> str:
    res = await client.post(
        "/api/drivers", headers=headers, json={"name": name, "license_number": f"L-{name}"}
    )
    assert res.status_code == 200, res.text
    return res.json()["id"]


async def _set_login(client: AsyncClient, headers: dict, driver_id: str, login: str, password: str):
    return await client.post(
        f"/api/drivers/{driver_id}/create-login",
        headers=headers,
        json={"login": login, "password": password},
    )


async def _login(client: AsyncClient, login: str, password: str):
    return await client.post("/api/auth/login", json={"login": login, "password": password})


async def test_a_driver_signs_in_with_a_plain_login(client: AsyncClient, admin_headers):
    driver_id = await _driver(client, admin_headers)
    res = await _set_login(client, admin_headers, driver_id, "10422tca", "driverpass123")
    assert res.status_code == 201, res.text
    assert res.json()["login"] == "10422tca"

    assert (await _login(client, "10422tca", "driverpass123")).status_code == 200


async def test_the_login_ignores_case_either_way(client: AsyncClient, admin_headers):
    driver_id = await _driver(client, admin_headers)
    res = await _set_login(client, admin_headers, driver_id, "10422TCA", "driverpass123")
    assert res.status_code == 201, res.text
    assert res.json()["login"] == "10422tca"

    for typed in ("10422tca", "10422TCA", " 10422Tca "):
        assert (await _login(client, typed, "driverpass123")).status_code == 200, typed


async def test_staff_email_login_ignores_case_too(client: AsyncClient, admin_token):
    assert (await _login(client, "ADMIN@test.com", "password123")).status_code == 200


async def test_the_old_app_still_signs_in_with_the_email_field(client: AsyncClient, admin_headers):
    """Phones in the field run the previous build, which posts ``email``."""
    driver_id = await _driver(client, admin_headers)
    await _set_login(client, admin_headers, driver_id, "old.phone", "driverpass123")
    res = await client.post(
        "/api/auth/login", json={"email": "old.phone", "password": "driverpass123"}
    )
    assert res.status_code == 200, res.text


async def test_an_email_is_still_a_valid_login(client: AsyncClient, admin_headers):
    driver_id = await _driver(client, admin_headers)
    res = await _set_login(client, admin_headers, driver_id, "Driver@Mail.com", "driverpass123")
    assert res.status_code == 201, res.text
    assert (await _login(client, "driver@mail.com", "driverpass123")).status_code == 200


async def test_a_login_with_spaces_is_refused(client: AsyncClient, admin_headers):
    driver_id = await _driver(client, admin_headers)
    res = await _set_login(client, admin_headers, driver_id, "10 422 TCA", "driverpass123")
    assert res.status_code == 422


async def test_a_login_someone_else_holds_is_refused(client: AsyncClient, admin_headers):
    first = await _driver(client, admin_headers, "First")
    second = await _driver(client, admin_headers, "Second")
    assert (await _set_login(client, admin_headers, first, "truck1", "driverpass123")).status_code == 201

    res = await _set_login(client, admin_headers, second, "TRUCK1", "driverpass123")
    assert res.status_code == 400


async def test_resetting_replaces_the_login_and_the_password(client: AsyncClient, admin_headers):
    driver_id = await _driver(client, admin_headers)
    await _set_login(client, admin_headers, driver_id, "10422tca@gmail.com", "oldpassword1")
    old = await _login(client, "10422tca@gmail.com", "oldpassword1")
    old_headers = {"Authorization": f"Bearer {old.json()['access_token']}"}

    res = await _set_login(client, admin_headers, driver_id, "10422tca", "newpassword1")
    assert res.status_code == 201, res.text

    assert (await _login(client, "10422tca@gmail.com", "oldpassword1")).status_code == 401
    assert (await _login(client, "10422tca", "oldpassword1")).status_code == 401
    assert (await _login(client, "10422tca", "newpassword1")).status_code == 200
    # The phone signed in under the old password is signed out.
    assert (await client.get("/api/auth/me", headers=old_headers)).status_code == 401


async def test_resetting_keeps_the_same_login_if_only_the_password_changes(
    client: AsyncClient, admin_headers
):
    driver_id = await _driver(client, admin_headers)
    await _set_login(client, admin_headers, driver_id, "truck7", "oldpassword1")
    res = await _set_login(client, admin_headers, driver_id, "truck7", "newpassword1")
    assert res.status_code == 201, res.text
    assert (await _login(client, "truck7", "newpassword1")).status_code == 200


async def test_the_panel_can_read_a_drivers_current_login(client: AsyncClient, admin_headers):
    driver_id = await _driver(client, admin_headers)
    res = await client.get(f"/api/drivers/{driver_id}/login", headers=admin_headers)
    assert res.status_code == 200
    assert res.json() == {"login": None}

    await _set_login(client, admin_headers, driver_id, "truck9", "driverpass123")
    res = await client.get(f"/api/drivers/{driver_id}/login", headers=admin_headers)
    assert res.json() == {"login": "truck9"}


async def test_another_fleets_driver_login_is_not_readable(
    client: AsyncClient, admin_headers
):
    driver_id = await _driver(client, admin_headers)
    await client.post(
        "/api/auth/register",
        json={"email": "rival@test.com", "password": "password123", "org_name": "Rival"},
    )
    rival = await _login(client, "rival@test.com", "password123")
    rival_headers = {"Authorization": f"Bearer {rival.json()['access_token']}"}

    res = await client.get(f"/api/drivers/{driver_id}/login", headers=rival_headers)
    assert res.status_code == 404
    res = await _set_login(client, rival_headers, driver_id, "hijack", "driverpass123")
    assert res.status_code == 404
