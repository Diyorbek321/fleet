"""Authenticating a GPS tracker without paying bcrypt on every ping.

A tracker re-presents the *same* API key every fifteen seconds for years. The
key itself is 32 bytes of ``secrets.token_urlsafe`` — there is no dictionary to
walk and no human-chosen password to slow an attacker down on, which is the
only thing bcrypt's cost factor buys. Verifying it costs ~200 ms all the same,
and until this module existed that ran synchronously inside the request
coroutine: every ingest froze the whole event loop for a quarter of a second,
so the live map, the WebSocket feed and every unrelated API call queued behind
a truck saying it had moved ten metres.

Two independent problems, two fixes, and both are needed:

* **Throughput** — a verified ``(imei, key)`` pair is remembered for
  :data:`TTL_SECONDS`, so the repeat presentation costs a SHA-256 instead of a
  bcrypt. The cache holds a *fingerprint* of the key, never the key.
* **Blocking** — a cache miss (and every wrong key, which is never cached)
  runs bcrypt in a worker thread. Without this an attacker spraying bad keys
  would stall the event loop just as effectively as the honest traffic used to.

The cache is per-process and deliberately not shared: it is an optimisation, so
a second replica simply pays the first verification itself, and a restart costs
one bcrypt per device. Correctness never depends on it — a stale entry can only
be created by a key change, and :func:`invalidate` is called on every path that
changes one.
"""
from __future__ import annotations

import hashlib
import hmac
from time import monotonic

from starlette.concurrency import run_in_threadpool

from app.core.security import verify_password

# Long enough that a 15-second ping never re-verifies, short enough that a
# rotation missed by an explicit invalidate (another replica's rotate call)
# still heals on its own within minutes.
TTL_SECONDS = 300

# A fleet is hundreds of devices, not thousands; the ceiling exists so a flood
# of unknown IMEIs cannot grow the dict without bound, not because a real
# deployment approaches it.
MAX_ENTRIES = 10_000

# imei -> (key fingerprint, expiry on the monotonic clock)
_verified: dict[str, tuple[str, float]] = {}


def _fingerprint(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def invalidate(imei: str | None) -> None:
    """Forget a device's cached verification. Safe to call for unknown IMEIs."""
    if imei:
        _verified.pop(imei, None)


def clear() -> None:
    """Drop every entry. Used by tests and on nothing else."""
    _verified.clear()


def _evict_if_needed(now: float) -> None:
    if len(_verified) < MAX_ENTRIES:
        return
    for imei in [k for k, (_, exp) in _verified.items() if exp <= now]:
        _verified.pop(imei, None)
    if len(_verified) >= MAX_ENTRIES:
        # Still full of live entries: this is not a real fleet, it is a flood.
        # Dropping everything costs one bcrypt per genuine device and bounds
        # the damage; keeping a partial set would just pick arbitrary winners.
        _verified.clear()


async def verify_device_key(imei: str, api_key: str, api_key_hash: str) -> bool:
    """Whether ``api_key`` matches this device's stored hash.

    Never raises for a bad key — returns ``False`` so the caller decides what a
    failure means.
    """
    now = monotonic()
    fingerprint = _fingerprint(api_key)

    cached = _verified.get(imei)
    if cached is not None:
        cached_fingerprint, expires_at = cached
        if expires_at > now and hmac.compare_digest(cached_fingerprint, fingerprint):
            return True
        if expires_at <= now:
            _verified.pop(imei, None)

    # Off the event loop: bcrypt is CPU-bound and deliberately slow, and this
    # branch is reachable by anyone who can guess an IMEI.
    ok = await run_in_threadpool(verify_password, api_key, api_key_hash)
    if ok:
        _evict_if_needed(now)
        _verified[imei] = (fingerprint, now + TTL_SECONDS)
    return ok
