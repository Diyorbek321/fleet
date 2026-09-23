"""Device key verification: fast on the happy path, never on the event loop.

A tracker presents the same key every fifteen seconds. Verifying it with bcrypt
costs ~200 ms of CPU, and that used to run inside the request coroutine — so
the ingest endpoint stalled the whole process for a quarter second per ping.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.core.security import hash_password
from app.services import device_auth


@pytest.fixture(autouse=True)
def _clean_cache():
    device_auth.clear()
    yield
    device_auth.clear()


async def test_correct_key_verifies():
    key = "device-key-abc123"
    assert await device_auth.verify_device_key("111", key, hash_password(key)) is True


async def test_wrong_key_is_rejected_and_not_remembered():
    """A failure must never seed the cache, or one guess would buy a session."""
    stored = hash_password("the-real-key")
    assert await device_auth.verify_device_key("111", "wrong", stored) is False
    assert "111" not in device_auth._verified


def counting_hashes(monkeypatch) -> "list[int]":
    """Count real bcrypt verifications, rather than timing them.

    A wall-clock assertion would pass or fail on how busy the machine is; the
    question here is exactly how many times the expensive call happened.
    """
    calls = [0]
    real = device_auth.verify_password

    def counted(password: str, password_hash: str) -> bool:
        calls[0] += 1
        return real(password, password_hash)

    monkeypatch.setattr(device_auth, "verify_password", counted)
    return calls


async def test_repeat_verification_skips_bcrypt(monkeypatch):
    """The second presentation of the same key must not cost another hash."""
    key = "device-key-abc123"
    stored = hash_password(key)
    hashes = counting_hashes(monkeypatch)

    assert await device_auth.verify_device_key("111", key, stored) is True
    assert await device_auth.verify_device_key("111", key, stored) is True

    assert hashes[0] == 1, f"bcrypt ran {hashes[0]} times for one device key"


async def test_a_different_key_on_a_cached_imei_is_still_checked():
    """The cache is keyed by IMEI; it must not authenticate any key for it."""
    key = "device-key-abc123"
    stored = hash_password(key)
    await device_auth.verify_device_key("111", key, stored)

    assert await device_auth.verify_device_key("111", "another-key", stored) is False


async def test_an_expired_entry_is_re_verified(monkeypatch):
    """Past its TTL the entry is worth nothing and the hash is consulted again."""
    key = "device-key-abc123"
    stored = hash_password(key)
    monkeypatch.setattr(device_auth, "TTL_SECONDS", -1)  # every entry is born stale
    hashes = counting_hashes(monkeypatch)

    assert await device_auth.verify_device_key("111", key, stored) is True
    assert await device_auth.verify_device_key("111", key, stored) is True

    assert hashes[0] == 2, "an expired entry was treated as a hit"

    # And a stale entry is no shortcut for the wrong key either.
    assert await device_auth.verify_device_key("111", "wrong", stored) is False


async def test_cache_is_bounded(monkeypatch):
    """An unknown-IMEI flood must not grow the dict without limit."""
    monkeypatch.setattr(device_auth, "MAX_ENTRIES", 4)
    stored = hash_password("k")
    for i in range(12):
        await device_auth.verify_device_key(f"imei-{i}", "k", stored)
    assert len(device_auth._verified) <= device_auth.MAX_ENTRIES


# ── Invalidation through the API ──────────────────────────────────────


async def _enroll(client: AsyncClient, headers: dict, imei: str) -> tuple[str, str]:
    res = await client.post("/api/devices", headers=headers, json={"imei": imei})
    body = res.json()
    return body["id"], body["api_key"]


async def test_rotating_a_key_stops_the_old_one_immediately(
    client: AsyncClient, admin_headers
):
    """Not "within five minutes" — a rotation is usually a compromise."""
    imei = "352094081111111"
    device_id, old_key = await _enroll(client, admin_headers, imei)

    first = await client.post(
        "/api/gps/ingest",
        headers={"X-API-Key": old_key, "X-IMEI": imei},
        json={"points": [{"latitude": 41.3, "longitude": 69.2}]},
    )
    assert first.status_code == 200  # and now the key is cached

    rotated = await client.post(
        f"/api/devices/{device_id}/rotate-key", headers=admin_headers
    )
    assert rotated.status_code == 200
    new_key = rotated.json()["api_key"]

    stale = await client.post(
        "/api/gps/ingest",
        headers={"X-API-Key": old_key, "X-IMEI": imei},
        json={"points": [{"latitude": 41.3, "longitude": 69.2}]},
    )
    assert stale.status_code == 401, "the rotated-away key still authenticates"

    fresh = await client.post(
        "/api/gps/ingest",
        headers={"X-API-Key": new_key, "X-IMEI": imei},
        json={"points": [{"latitude": 41.3, "longitude": 69.2}]},
    )
    assert fresh.status_code == 200


async def test_deleting_a_device_stops_its_key_immediately(
    client: AsyncClient, admin_headers
):
    imei = "352094082222222"
    device_id, key = await _enroll(client, admin_headers, imei)
    await client.post(
        "/api/gps/ingest",
        headers={"X-API-Key": key, "X-IMEI": imei},
        json={"points": [{"latitude": 41.3, "longitude": 69.2}]},
    )

    assert (await client.delete(f"/api/devices/{device_id}", headers=admin_headers)).status_code == 204

    res = await client.post(
        "/api/gps/ingest",
        headers={"X-API-Key": key, "X-IMEI": imei},
        json={"points": [{"latitude": 41.3, "longitude": 69.2}]},
    )
    assert res.status_code == 401
