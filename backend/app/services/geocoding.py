"""Turn a GPS fix into a place a person recognises: country first, then city.

Every location this platform ever showed an owner was a pair of decimal degrees
behind a Google Maps link. But "где груз?" is answered by *"Казахстан,
Sariog'ash"*, not by ``41.0167, 70.1436`` — and nobody reading a Telegram
message on a phone opens a map to find out which country their lorry is in.
That gap is what this module closes; ``telegram.py``'s ``_fmt_coords`` has
carried the note "reverse-geocoding is a V2 job" since the bot was written.

Three constraints shaped the code, in this order:

**A message must never fail because a geocoder did.** Every public function
returns ``None`` on any error — HTTP 500, a timeout, rate limiting, HTML where
JSON was promised, DNS down — and the callers fall back to the bare map link
they printed before. The location line is decoration on a notification, never a
precondition for sending it.

**Nominatim's usage policy is a hard limit, not a suggestion.** One request per
second and a User-Agent that identifies us. Exceeding it gets the IP blocked,
which takes the feature down for every customer at once, so the politeness gap
is enforced here rather than trusted to callers. Note the scope: the gap is
process-wide, which equals platform-wide only because the API runs as a single
uvicorn process in one container. Add replicas or ``--workers`` and each one
gets its own budget — at which point this needs the Redis lease that
``scheduler.py::_run_locked`` already uses for exactly that reason.

**Trucks stand still.** A parked lorry pinging every 30 seconds is the same
place every time. Coordinates are snapped to a ~1 km grid before they become a
cache key, so a stationary truck costs one lookup per grid cell per month
instead of one per ping. The cache is checked in memory first, then Redis (so
all replicas share one answer), and only then does anyone call out.

The provider is behind ``settings.geocoding_url`` and the parsing is confined
to :func:`_parse`, so swapping Nominatim for Yandex later is one function and a
config change, not a rewrite of the notification path.
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import settings
from app.core.logging import logger

try:  # pragma: no cover - exercised only when redis is installed/enabled
    import redis.asyncio as aioredis
except Exception:  # pragma: no cover
    aioredis = None


# Decimal places kept in a cache key. Two ≈ 1.1 km at this latitude, which is
# below the resolution of the answer we ask for (a city), so snapping costs no
# accuracy. Points either side of a rounding boundary simply cost one extra
# lookup — never a wrong answer.
_CACHE_PRECISION = 2

# Upper bound on the in-process cache. A fleet crossing Eurasia touches a few
# thousand grid cells a month; this is generous and keeps the dict from growing
# without limit in a long-lived container.
_MEMORY_CACHE_MAX = 20_000

_REDIS_PREFIX = "geo:rev:"


# Russian names for the countries this platform's corridors actually run
# through. Nominatim honours ``accept-language=ru`` for most of them, but its
# coverage is inconsistent (it will happily answer "Kazakhstan"), and a country
# name is the one word in the message that must not wobble between languages.
# Anything not listed keeps whatever the provider called it.
_COUNTRY_RU: dict[str, str] = {
    "uz": "Узбекистан",
    "kz": "Казахстан",
    "ru": "Россия",
    "kg": "Кыргызстан",
    "tj": "Таджикистан",
    "tm": "Туркменистан",
    "af": "Афганистан",
    "cn": "Китай",
    "tr": "Турция",
    "ir": "Иран",
    "az": "Азербайджан",
    "ge": "Грузия",
    "am": "Армения",
    "by": "Беларусь",
    "ua": "Украина",
}

# Narrowest recognisable settlement first. A driver stopped between towns gets
# the district or region rather than nothing at all — "Казахстан, Сарыагашский
# район" is still an answer; "Казахстан" alone is nearly one.
_LOCALITY_KEYS: tuple[str, ...] = (
    "city",
    "town",
    "village",
    "hamlet",
    "municipality",
    "city_district",
    "county",
    "state_district",
    "state",
    "region",
)


@dataclass(frozen=True)
class Place:
    """Where a coordinate is, in the words a message will use."""

    country_code: str | None
    country: str | None
    locality: str | None

    @property
    def label(self) -> str | None:
        """One line: ``"Казахстан, Сарыагаш"``, or the half that is known.

        Returns ``None`` when nothing is known, which is the caller's signal to
        print the map link alone rather than an empty bullet.
        """
        country = (self.country or "").strip()
        locality = (self.locality or "").strip()
        # City-states and provider quirks answer with the same word twice.
        # "Сингапур, Сингапур" reads like a bug, so collapse it.
        if country and locality and locality.casefold() != country.casefold():
            return f"{country}, {locality}"
        return country or locality or None


def country_name_ru(code: str | None, fallback: str | None) -> str | None:
    """Russian name for an ISO 3166-1 alpha-2 code, else what the provider said."""
    if not code:
        return fallback
    return _COUNTRY_RU.get(code.strip().lower(), fallback)


def cache_key(lat: float, lng: float) -> str:
    """Grid cell (~1 km) a coordinate falls in. See ``_CACHE_PRECISION``."""
    return f"{round(float(lat), _CACHE_PRECISION)}:{round(float(lng), _CACHE_PRECISION)}"


# ── Cache ────────────────────────────────────────────────────────────────

# key -> (expires_at_monotonic, Place)
_memory: dict[str, tuple[float, Place]] = {}
_redis_client: Any = None


def clear_cache() -> None:
    """Drop the in-process cache. Used by tests; harmless in production."""
    _memory.clear()


def _ttl_seconds() -> int:
    return max(60, settings.geocoding_cache_ttl_days * 86_400)


def _memory_get(key: str) -> Place | None:
    hit = _memory.get(key)
    if hit is None:
        return None
    expires_at, place = hit
    if expires_at < time.monotonic():
        _memory.pop(key, None)
        return None
    return place


def _memory_put(key: str, place: Place) -> None:
    if len(_memory) >= _MEMORY_CACHE_MAX:
        # Cheap eviction: this is a cache, not an index. Dropping the oldest
        # inserted key is enough to bound memory without tracking usage.
        _memory.pop(next(iter(_memory)), None)
    _memory[key] = (time.monotonic() + _ttl_seconds(), place)


async def _redis_get(key: str) -> Place | None:
    """Shared cache lookup. Any Redis trouble degrades to a provider call."""
    client = _get_redis()
    if client is None:
        return None
    try:
        raw = await client.get(_REDIS_PREFIX + key)
    except Exception:  # noqa: BLE001 — a cache miss is always a safe answer
        logger.warning("geocode_cache_read_failed", key=key)
        return None
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return Place(
            country_code=data.get("country_code"),
            country=data.get("country"),
            locality=data.get("locality"),
        )
    except Exception:  # noqa: BLE001
        return None


async def _redis_put(key: str, place: Place) -> None:
    client = _get_redis()
    if client is None:
        return
    try:
        await client.set(
            _REDIS_PREFIX + key,
            json.dumps(
                {
                    "country_code": place.country_code,
                    "country": place.country,
                    "locality": place.locality,
                }
            ),
            ex=_ttl_seconds(),
        )
    except Exception:  # noqa: BLE001 — failing to cache is not failing
        logger.warning("geocode_cache_write_failed", key=key)


def _get_redis():
    global _redis_client
    if not settings.redis_enabled or aioredis is None:
        return None
    if _redis_client is None:
        try:
            _redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
        except Exception:  # noqa: BLE001
            logger.warning("geocode_redis_init_failed")
            return None
    return _redis_client


# ── Politeness gap ───────────────────────────────────────────────────────

_gap_lock = asyncio.Lock()
_last_request_at: float = 0.0


async def _respect_rate_limit() -> None:
    """Hold the caller until at least ``geocoding_min_interval_s`` has passed.

    Serialised through one lock so concurrent notification batches queue behind
    each other instead of all firing at once — the batch is what would trip the
    provider's limiter, not the steady state. The lock is held *across* the
    sleep on purpose: releasing it first would let every waiter wake together
    and fire simultaneously, which is the burst this exists to prevent.

    Single-process only; see the module docstring.
    """
    gap = float(settings.geocoding_min_interval_s)
    if gap <= 0:
        return
    global _last_request_at
    async with _gap_lock:
        wait = _last_request_at + gap - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)
        _last_request_at = time.monotonic()


# ── Provider ─────────────────────────────────────────────────────────────


def _pick_locality(address: dict) -> str | None:
    """Narrowest named settlement in a Nominatim address block."""
    for key in _LOCALITY_KEYS:
        value = address.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _parse(body: Any) -> Place | None:
    """Nominatim ``jsonv2`` body → :class:`Place`, or ``None`` if it said nothing.

    The one place that knows the provider's response shape.
    """
    if not isinstance(body, dict):
        return None
    address = body.get("address")
    if not isinstance(address, dict) or not address:
        return None

    code = address.get("country_code")
    code = code.strip().lower() if isinstance(code, str) and code.strip() else None
    raw_country = address.get("country")
    raw_country = raw_country.strip() if isinstance(raw_country, str) else None

    return Place(
        country_code=code,
        country=country_name_ru(code, raw_country),
        locality=_pick_locality(address),
    )


async def _fetch(lat: float, lng: float, *, transport: httpx.BaseTransport | None = None) -> Place | None:
    """One provider round-trip. Never raises."""
    params = {
        "format": "jsonv2",
        "lat": lat,
        "lon": lng,
        "zoom": settings.geocoding_zoom,
        "addressdetails": 1,
        "accept-language": settings.geocoding_language,
    }
    headers = {"User-Agent": settings.geocoding_user_agent}

    try:
        await _respect_rate_limit()
        async with httpx.AsyncClient(
            timeout=settings.geocoding_timeout_s, transport=transport, headers=headers
        ) as client:
            resp = await client.get(settings.geocoding_url, params=params)
        if resp.status_code != 200:
            # 429 means we are being told to slow down; log it loudly enough to
            # notice, because the fix is configuration, not code.
            logger.warning("geocode_provider_status", status=resp.status_code, lat=lat, lng=lng)
            return None
        # Parsing stays inside the guard on purpose. ``_parse`` is defensive
        # today, but "never raises" has to be structural: the one caller that
        # would suffer most (the morning digest) loops over subscribers, and an
        # exception escaping here would abort the whole batch rather than one
        # message.
        return _parse(resp.json())
    except Exception:  # noqa: BLE001 — a missing place must never break a message
        logger.warning("geocode_provider_unreachable", lat=lat, lng=lng)
        return None


# ── Public API ───────────────────────────────────────────────────────────


async def reverse(
    lat: float | None,
    lng: float | None,
    *,
    transport: httpx.BaseTransport | None = None,
) -> Place | None:
    """Where is this coordinate? ``None`` when unknown, unreachable or disabled.

    Cached in memory and in Redis; a failed lookup is deliberately *not*
    cached, so a provider outage does not poison the answer for a month.
    """
    if not settings.geocoding_enabled:
        return None
    if lat is None or lng is None:
        return None

    key = cache_key(lat, lng)

    cached = _memory_get(key)
    if cached is not None:
        return cached

    shared = await _redis_get(key)
    if shared is not None:
        _memory_put(key, shared)
        return shared

    place = await _fetch(lat, lng, transport=transport)
    if place is None:
        return None

    _memory_put(key, place)
    await _redis_put(key, place)
    return place


async def describe(
    lat: float | None,
    lng: float | None,
    *,
    transport: httpx.BaseTransport | None = None,
) -> str | None:
    """The one-line label for a coordinate, ready to drop into a message."""
    place = await reverse(lat, lng, transport=transport)
    return place.label if place else None
