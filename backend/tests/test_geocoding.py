"""Koordinatani odam tushunadigan joyga aylantirish.

The interesting failures here are not wrong cities. They are:

* a Telegram message that never goes out because a geocoder was slow or down —
  the location line is decoration, the message is the product;
* our IP banned by Nominatim because a parked lorry pinging every 30 seconds
  turned into four hundred identical lookups a day.

So most of what follows is about the degraded paths and the cache, not about
the happy one.
"""
from __future__ import annotations

import json

import httpx
import pytest

from app.core.config import settings
from app.models.enums import TripStatus
from app.services import geocoding
from app.services.geocoding import Place, country_name_ru, reverse
from app.services.telegram import format_daily_update, format_status_change


def _responder(payload: dict, status_code: int = 200, *, counter: list | None = None):
    """MockTransport handler returning one canned Nominatim body."""

    def handler(request: httpx.Request) -> httpx.Response:
        if counter is not None:
            counter.append(str(request.url))
        return httpx.Response(status_code, json=payload)

    return httpx.MockTransport(handler)


_SARYAGASH = {
    "address": {
        "town": "Sariog'ash",
        "county": "Sariog'ash tumani",
        "state": "Turkiston viloyati",
        "country": "Казахстан",
        "country_code": "kz",
    }
}


@pytest.fixture(autouse=True)
def _enabled_and_unthrottled(monkeypatch):
    """Geocoding is off in the test env by default; these tests want it on,
    without the one-second politeness gap or a warm cache between cases."""
    monkeypatch.setattr(settings, "geocoding_enabled", True, raising=False)
    monkeypatch.setattr(settings, "geocoding_min_interval_s", 0.0, raising=False)
    geocoding.clear_cache()
    yield
    geocoding.clear_cache()


# ── The label a human reads ──────────────────────────────────────────────


def test_label_puts_country_first_then_locality():
    place = Place(country_code="kz", country="Казахстан", locality="Sariog'ash tumani")
    assert place.label == "Казахстан, Sariog'ash tumani"


def test_label_is_country_alone_when_locality_unknown():
    assert Place(country_code="uz", country="Узбекистан", locality=None).label == "Узбекистан"


def test_label_is_locality_alone_when_country_unknown():
    assert Place(country_code=None, country=None, locality="Angren").label == "Angren"


def test_label_is_none_when_nothing_is_known():
    assert Place(country_code=None, country=None, locality=None).label is None


def test_label_does_not_repeat_a_locality_equal_to_the_country():
    """Singapore-shaped answers: "Singapur, Singapur" reads like a bug."""
    place = Place(country_code="sg", country="Singapur", locality="Singapur")
    assert place.label == "Singapur"


# ── Country names in Uzbek ───────────────────────────────────────────────


@pytest.mark.parametrize(
    "code,expected",
    [
        ("uz", "Узбекистан"),
        ("kz", "Казахстан"),
        ("ru", "Россия"),
        ("kg", "Кыргызстан"),
        ("tj", "Таджикистан"),
        ("tm", "Туркменистан"),
        ("cn", "Китай"),
        ("tr", "Турция"),
        ("af", "Афганистан"),
        ("KZ", "Казахстан"),  # case-insensitive
    ],
)
def test_corridor_countries_are_named_in_russian(code, expected):
    assert country_name_ru(code, fallback="ignored") == expected


def test_unknown_country_keeps_whatever_the_provider_called_it():
    assert country_name_ru("zz", fallback="Zanzibar") == "Zanzibar"


def test_missing_country_code_falls_back_too():
    assert country_name_ru(None, fallback="Kazakhstan") == "Kazakhstan"


# ── Cache key: a parked lorry must cost one lookup, not hundreds ─────────


def test_points_within_about_a_kilometre_share_a_cache_key():
    a = geocoding.cache_key(41.01670, 70.14360)
    b = geocoding.cache_key(41.01679, 70.14369)
    assert a == b


def test_points_far_apart_do_not_share_a_cache_key():
    assert geocoding.cache_key(41.0167, 70.1436) != geocoding.cache_key(43.2220, 76.8512)


# ── The provider call ────────────────────────────────────────────────────


async def test_reverse_reads_country_and_locality_from_the_provider():
    place = await reverse(41.0167, 70.1436, transport=_responder(_SARYAGASH))
    assert place is not None
    assert place.country_code == "kz"
    assert place.country == "Казахстан"
    assert place.locality == "Sariog'ash"
    assert place.label == "Казахстан, Sariog'ash"


@pytest.mark.parametrize(
    "address,expected",
    [
        ({"city": "Toshkent", "town": "x", "village": "y"}, "Toshkent"),
        ({"town": "Angren", "village": "y"}, "Angren"),
        ({"village": "Yallama"}, "Yallama"),
        ({"municipality": "Chirchiq"}, "Chirchiq"),
        ({"county": "Sariog'ash tumani"}, "Sariog'ash tumani"),
        ({"state": "Turkiston viloyati"}, "Turkiston viloyati"),
        ({}, None),
    ],
)
async def test_locality_follows_a_narrowest_first_preference(address, expected):
    payload = {"address": {**address, "country": "X", "country_code": "xx"}}
    place = await reverse(41.0, 70.0, transport=_responder(payload))
    assert place is not None and place.locality == expected


async def test_second_lookup_of_the_same_place_does_not_call_the_provider():
    calls: list[str] = []
    transport = _responder(_SARYAGASH, counter=calls)
    await reverse(41.0167, 70.1436, transport=transport)
    await reverse(41.01679, 70.14369, transport=transport)  # ~10 m away
    assert len(calls) == 1


async def test_the_request_asks_for_russian_and_a_settlement_level_zoom():
    calls: list[str] = []
    await reverse(41.0167, 70.1436, transport=_responder(_SARYAGASH, counter=calls))
    url = calls[0]
    assert "lat=41.0167" in url and "lon=70.1436" in url
    assert "accept-language=ru" in url
    assert "format=jsonv2" in url


# ── Every degraded path returns None instead of raising ──────────────────


async def test_provider_error_yields_no_place():
    assert await reverse(41.0, 70.0, transport=_responder({}, status_code=500)) is None


async def test_rate_limited_response_yields_no_place():
    assert await reverse(41.0, 70.0, transport=_responder({}, status_code=429)) is None


async def test_malformed_body_yields_no_place():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<html>not json</html>")

    assert await reverse(41.0, 70.0, transport=httpx.MockTransport(handler)) is None


async def test_body_without_an_address_yields_no_place():
    assert await reverse(41.0, 70.0, transport=_responder({"error": "Unable to geocode"})) is None


async def test_network_failure_yields_no_place():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host")

    assert await reverse(41.0, 70.0, transport=httpx.MockTransport(handler)) is None


async def test_a_failed_lookup_is_not_cached_as_a_success():
    """A geocoder outage must not poison the cache for the next 30 days."""
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if len(calls) == 1:
            return httpx.Response(503)
        return httpx.Response(200, json=_SARYAGASH)

    transport = httpx.MockTransport(handler)
    assert await reverse(41.0167, 70.1436, transport=transport) is None
    place = await reverse(41.0167, 70.1436, transport=transport)
    assert place is not None and place.country == "Казахстан"


async def test_disabled_geocoding_makes_no_request_at_all(monkeypatch):
    monkeypatch.setattr(settings, "geocoding_enabled", False, raising=False)
    calls: list[str] = []
    assert await reverse(41.0, 70.0, transport=_responder(_SARYAGASH, counter=calls)) is None
    assert calls == []


async def test_describe_is_the_label_or_none():
    assert await geocoding.describe(41.0167, 70.1436, transport=_responder(_SARYAGASH)) == (
        "Казахстан, Sariog'ash"
    )
    geocoding.clear_cache()
    assert await geocoding.describe(41.0, 70.0, transport=_responder({}, status_code=500)) is None


# ── How it reads in the message ──────────────────────────────────────────


def test_status_change_message_names_the_country_and_city():
    text = format_status_change(
        "TR-42", TripStatus.at_border, 41.0, 70.0, place="Казахстан, Sariog'ash"
    )
    assert "Казахстан, Sariog'ash" in text
    assert "41.0,70.0" in text  # the map link survives


def test_status_change_message_without_a_place_is_what_it_always_was():
    text = format_status_change("TR-42", TripStatus.at_border, 41.0, 70.0)
    assert "41.0,70.0" in text
    assert "посмотреть на карте" in text


def test_daily_update_names_the_place_too():
    text = format_daily_update(
        "TR-77", TripStatus.en_route, 41.0, 70.0, "Almaty", 60.0, None, place="Казахстан"
    )
    assert "Казахстан" in text


def test_place_is_escaped_so_a_city_name_cannot_inject_html():
    text = format_status_change("TR-1", TripStatus.en_route, 1.0, 2.0, place="<b>hack</b>")
    assert "<b>hack</b>" not in text
    assert "&lt;b&gt;hack&lt;/b&gt;" in text


# ── The politeness gap ───────────────────────────────────────────────────


async def test_concurrent_lookups_are_spaced_by_the_configured_gap(monkeypatch):
    """The burst is what gets an IP banned, so the lock must hold across the
    sleep — two callers racing for different cells may not fire together."""
    import asyncio
    import time as _time

    monkeypatch.setattr(settings, "geocoding_min_interval_s", 0.05, raising=False)

    fired: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        fired.append(_time.monotonic())
        return httpx.Response(200, json=_SARYAGASH)

    transport = httpx.MockTransport(handler)
    await asyncio.gather(
        reverse(41.00, 70.00, transport=transport),
        reverse(43.00, 76.00, transport=transport),
        reverse(55.00, 37.00, transport=transport),
    )

    assert len(fired) == 3
    gaps = [b - a for a, b in zip(sorted(fired), sorted(fired)[1:])]
    assert all(gap >= 0.04 for gap in gaps), gaps


async def test_a_cache_hit_does_not_wait_on_the_gap(monkeypatch):
    """Otherwise a warm fleet would still crawl through the morning batch."""
    import asyncio
    import time as _time

    await reverse(41.0167, 70.1436, transport=_responder(_SARYAGASH))

    monkeypatch.setattr(settings, "geocoding_min_interval_s", 5.0, raising=False)
    started = _time.monotonic()
    place = await asyncio.wait_for(reverse(41.0167, 70.1436), timeout=1.0)
    assert place is not None
    assert _time.monotonic() - started < 0.5
