"""A driver correcting the paperwork photos they sent: delete, relabel, retake.

What must hold: a driver can fix their own uploads while the trip is still
running, never someone else's, and never after delivery — once a trip is
delivered its CMR is what the money was settled on, and only the desk may
change it.
"""
from __future__ import annotations

import io
from pathlib import Path

import pytest
from httpx import AsyncClient

from app.core.config import settings

PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6360000002000100ffff03000006000557bfabd400"
    "00000049454e44ae426082"
)
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64 + b"\xff\xd9"


@pytest.fixture(autouse=True)
def _uploads_in_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))


def _stored_files() -> list[Path]:
    root = Path(settings.upload_dir)
    return [p for p in root.rglob("*") if p.is_file()] if root.exists() else []


async def _trip(client: AsyncClient, admin_headers, driver_login) -> str:
    truck = (await client.post("/api/trucks", headers=admin_headers,
                               json={"name": "Doc", "plate_number": "DOC-1"})).json()
    res = await client.post("/api/trips", headers=admin_headers,
                            json={"truck_id": truck["id"], "driver_id": driver_login["driver_id"]})
    assert res.status_code == 200, res.text
    return res.json()["id"]


async def _upload(client: AsyncClient, headers, trip_id: str, category: str = "cmr") -> dict:
    res = await client.post(
        f"/api/me/trips/{trip_id}/documents", headers=headers,
        files={"file": ("a.png", io.BytesIO(PNG), "image/png")},
        data={"category": category},
    )
    assert res.status_code == 201, res.text
    return res.json()


def _doc_url(trip_id: str, doc_id: str) -> str:
    return f"/api/me/trips/{trip_id}/documents/{doc_id}"


async def test_a_driver_deletes_a_wrong_photo(client: AsyncClient, admin_headers, driver_login):
    headers = driver_login["headers"]
    trip_id = await _trip(client, admin_headers, driver_login)
    doc = await _upload(client, headers, trip_id)
    assert len(_stored_files()) == 1

    res = await client.delete(_doc_url(trip_id, doc["id"]), headers=headers)

    assert res.status_code == 204, res.text
    listed = (await client.get(f"/api/me/trips/{trip_id}/documents", headers=headers)).json()
    assert listed == []
    assert _stored_files() == []  # the file goes too, not only the row


async def test_a_driver_relabels_a_photo(client: AsyncClient, admin_headers, driver_login):
    headers = driver_login["headers"]
    trip_id = await _trip(client, admin_headers, driver_login)
    doc = await _upload(client, headers, trip_id, category="cmr")

    res = await client.patch(_doc_url(trip_id, doc["id"]), headers=headers,
                             json={"category": "invoice", "caption": "2-bet"})

    assert res.status_code == 200, res.text
    assert res.json()["category"] == "invoice"
    assert res.json()["caption"] == "2-bet"


async def test_a_driver_retakes_a_photo_in_place(client: AsyncClient, admin_headers, driver_login):
    headers = driver_login["headers"]
    trip_id = await _trip(client, admin_headers, driver_login)
    doc = await _upload(client, headers, trip_id, category="cmr")

    res = await client.put(
        f"{_doc_url(trip_id, doc['id'])}/file", headers=headers,
        files={"file": ("b.jpg", io.BytesIO(JPEG), "image/jpeg")},
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["id"] == doc["id"]          # the same document, retaken
    assert body["category"] == "cmr"        # its label survives
    assert body["content_type"] == "image/jpeg"
    files = _stored_files()
    assert len(files) == 1 and files[0].suffix == ".jpg"  # the old photo is gone


async def test_after_delivery_the_driver_can_no_longer_change_it(
    client: AsyncClient, admin_headers, driver_login
):
    headers = driver_login["headers"]
    trip_id = await _trip(client, admin_headers, driver_login)
    doc = await _upload(client, headers, trip_id)
    await client.post(f"/api/trips/{trip_id}/advance", headers=admin_headers, json={"to_status": "delivered"})

    assert (await client.delete(_doc_url(trip_id, doc["id"]), headers=headers)).status_code == 409
    assert (await client.patch(_doc_url(trip_id, doc["id"]), headers=headers,
                               json={"category": "other"})).status_code == 409
    retake = await client.put(f"{_doc_url(trip_id, doc['id'])}/file", headers=headers,
                              files={"file": ("b.png", io.BytesIO(PNG), "image/png")})
    assert retake.status_code == 409
    # And it is all still there.
    assert len(_stored_files()) == 1


async def test_after_delivery_the_desk_still_can(client: AsyncClient, admin_headers, driver_login):
    headers = driver_login["headers"]
    trip_id = await _trip(client, admin_headers, driver_login)
    doc = await _upload(client, headers, trip_id, category="cmr")
    await client.post(f"/api/trips/{trip_id}/advance", headers=admin_headers, json={"to_status": "delivered"})

    res = await client.patch(f"/api/trips/{trip_id}/documents/{doc['id']}", headers=admin_headers,
                             json={"category": "customs", "caption": None})

    assert res.status_code == 200, res.text
    assert res.json()["category"] == "customs"


async def test_a_driver_cannot_touch_another_drivers_photo(
    client: AsyncClient, admin_headers, driver_login, db
):
    from app.models.trips import TripDocument
    from sqlalchemy import select

    headers = driver_login["headers"]
    trip_id = await _trip(client, admin_headers, driver_login)
    doc = await _upload(client, headers, trip_id)
    # Uploaded by the driver who had the trip before this one.
    row = (await db.execute(select(TripDocument))).scalar_one()
    row.driver_id = None
    await db.commit()

    assert (await client.delete(_doc_url(trip_id, doc["id"]), headers=headers)).status_code == 404
    assert (await client.patch(_doc_url(trip_id, doc["id"]), headers=headers,
                               json={"category": "x"})).status_code == 404


async def test_a_driver_cannot_reach_a_document_through_someone_elses_trip(
    client: AsyncClient, admin_headers, driver_login
):
    headers = driver_login["headers"]
    mine = await _trip(client, admin_headers, driver_login)
    doc = await _upload(client, headers, mine)
    other = (await client.post("/api/trips", headers=admin_headers, json={"rate": 1})).json()["id"]

    assert (await client.delete(_doc_url(other, doc["id"]), headers=headers)).status_code == 404


async def test_a_category_is_kept_short(client: AsyncClient, admin_headers, driver_login):
    headers = driver_login["headers"]
    trip_id = await _trip(client, admin_headers, driver_login)
    doc = await _upload(client, headers, trip_id)

    res = await client.patch(_doc_url(trip_id, doc["id"]), headers=headers, json={"category": "x" * 41})

    assert res.status_code == 422
