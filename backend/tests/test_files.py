"""Driver-uploaded documents: what gets in, and how it comes back out.

Uploads are photographed freight paperwork — the "yo'l varaqasi" a driver
shoots at a truck stop. The endpoint has to be strict about what it accepts
(the stored extension decides the Content-Type it will later be served as) and
careful about how it serves it back (signature-authorized, streamed, and never
open to reinterpretation by the browser).
"""
from __future__ import annotations

import io

import pytest
from httpx import AsyncClient

from app.core.config import settings


@pytest.fixture(autouse=True)
def _uploads_in_tmp(tmp_path, monkeypatch):
    """Write uploads under the test's tmp dir, not the container's /data volume."""
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))

# A 1x1 PNG — small enough to inline, real enough to be a valid upload.
PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6360000002000100ffff03000006000557bfabd400"
    "00000049454e44ae426082"
)


async def _trip_for_driver(client: AsyncClient, admin_headers, driver_login) -> str:
    """A trip owned by the logged-in driver, ready to hang a document on."""
    truck = await client.post(
        "/api/trucks", headers=admin_headers, json={"name": "Doc", "plate_number": "DOC-1"}
    )
    truck_id = truck.json()["id"]
    await client.post(
        f"/api/drivers/{driver_login['driver_id']}/assign",
        headers=admin_headers,
        json={"truck_id": truck_id},
    )
    trip = await client.post(
        "/api/trips",
        headers=admin_headers,
        json={"truck_id": truck_id, "driver_id": driver_login["driver_id"], "rate": 1000},
    )
    assert trip.status_code in (200, 201), trip.text
    return trip.json()["id"]


async def _upload(client: AsyncClient, headers, trip_id: str, name: str, ctype: str, data: bytes):
    return await client.post(
        f"/api/me/trips/{trip_id}/documents",
        headers=headers,
        files={"file": (name, io.BytesIO(data), ctype)},
    )


async def test_a_photo_uploads_and_comes_back_through_its_signed_url(
    client: AsyncClient, admin_headers, driver_login
):
    trip_id = await _trip_for_driver(client, admin_headers, driver_login)

    res = await _upload(
        client, driver_login["headers"], trip_id, "varaqa.png", "image/png", PNG_BYTES
    )
    assert res.status_code == 201, res.text

    url = res.json().get("url")
    assert url, f"no signed url in {res.json()}"

    fetched = await client.get(url.replace("http://testserver", ""))
    assert fetched.status_code == 200, fetched.text
    assert fetched.content == PNG_BYTES
    assert fetched.headers["content-type"].startswith("image/png")
    # The stored extension decides the type; the browser does not get to guess.
    assert fetched.headers["x-content-type-options"] == "nosniff"


async def test_an_svg_is_refused_rather_than_stored_unopenable(
    client: AsyncClient, admin_headers, driver_login
):
    """`image/svg+xml` is a scriptable document, not a photograph.

    It used to pass the `image/*` prefix check, get filed under `.bin`, and
    return 201 — an upload the driver believed had worked, attached to a trip
    whose document nobody could open.
    """
    trip_id = await _trip_for_driver(client, admin_headers, driver_login)

    res = await _upload(
        client,
        driver_login["headers"],
        trip_id,
        "sneaky.svg",
        "image/svg+xml",
        b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>",
    )
    assert res.status_code == 415, res.text


async def test_a_content_type_with_a_charset_suffix_is_still_accepted(
    client: AsyncClient, admin_headers, driver_login
):
    """Clients tack `;charset=` onto multipart parts; that is not a new type."""
    trip_id = await _trip_for_driver(client, admin_headers, driver_login)

    res = await _upload(
        client,
        driver_login["headers"],
        trip_id,
        "varaqa.png",
        "image/png;charset=utf-8",
        PNG_BYTES,
    )
    assert res.status_code == 201, res.text


async def test_an_unsigned_or_tampered_link_is_refused(
    client: AsyncClient, admin_headers, driver_login
):
    trip_id = await _trip_for_driver(client, admin_headers, driver_login)
    res = await _upload(
        client, driver_login["headers"], trip_id, "varaqa.png", "image/png", PNG_BYTES
    )
    url = res.json()["url"].replace("http://testserver", "")
    path = url.split("?")[0]

    assert (await client.get(path)).status_code == 422  # no exp/sig at all
    assert (await client.get(f"{path}?exp=9999999999&sig=deadbeef")).status_code == 403


async def test_an_expired_link_is_refused(
    client: AsyncClient, admin_headers, driver_login
):
    """The signature covers the expiry, so a caller cannot extend their own link."""
    trip_id = await _trip_for_driver(client, admin_headers, driver_login)
    res = await _upload(
        client, driver_login["headers"], trip_id, "varaqa.png", "image/png", PNG_BYTES
    )
    url = res.json()["url"].replace("http://testserver", "")
    path, query = url.split("?", 1)
    params = dict(p.split("=", 1) for p in query.split("&"))

    stale = await client.get(f"{path}?exp=1&sig={params['sig']}")
    assert stale.status_code == 403


async def test_the_schema_still_builds_with_this_router_mounted(client: AsyncClient):
    """/openapi.json must survive the file route.

    This module declares ``from __future__ import annotations``, so the
    ``-> FileResponse`` return annotation reaches FastAPI as a string. Without
    an explicit ``response_model=None`` FastAPI tries to build a pydantic
    TypeAdapter out of that unresolved ForwardRef and every schema request
    raises PydanticUserError — while the endpoint itself keeps answering 200,
    which is exactly how this reached production unnoticed.
    """
    res = await client.get("/openapi.json")
    assert res.status_code == 200
    assert "/api/files/{key}" in res.json()["paths"]
