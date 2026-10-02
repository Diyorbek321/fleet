"""The public tracking page: what a link holder sees, and what they must not.

The token in the URL is the whole credential — the customer has no account
here and never will. So the interesting tests are the negative ones: a wrong
token, a finished trip, and everything about the fleet that is deliberately
absent from a response that anyone on the internet can fetch.
"""
from __future__ import annotations

from httpx import AsyncClient

from app.core import urls
from app.core.config import settings


async def _trip_with_truck(client: AsyncClient, headers: dict) -> tuple[str, str]:
    truck = (
        await client.post(
            "/api/trucks",
            headers=headers,
            json={"name": "Alpha", "plate_number": "10 990 NBA"},
        )
    ).json()
    trip = (
        await client.post(
            "/api/trips",
            headers=headers,
            json={
                "truck_id": truck["id"],
                "origin_name": "Tobolsk",
                "destination_name": "Tashkent",
                "destination_lat": 41.3,
                "destination_lng": 69.2,
                "cargo_description": "Polypropylene",
                "rate": 45_000_000,
            },
        )
    ).json()
    return truck["id"], trip["id"]


async def _token_for(client: AsyncClient, headers: dict, trip_id: str, monkeypatch) -> str:
    monkeypatch.setattr(settings, "telegram_bot_username", "TestBot", raising=False)
    sub = (
        await client.post(
            "/api/trip-subscriptions", headers=headers, json={"trip_id": trip_id}
        )
    ).json()
    return sub["deep_link"].rsplit("trip_", 1)[1]


async def _move(client: AsyncClient, headers: dict, trip_id: str, to: str) -> None:
    res = await client.post(
        f"/api/trips/{trip_id}/advance", headers=headers, json={"to_status": to}
    )
    assert res.status_code == 200, res.text


async def test_a_link_holder_sees_the_load_without_signing_in(
    client: AsyncClient, admin_headers, monkeypatch
):
    _, trip_id = await _trip_with_truck(client, admin_headers)
    token = await _token_for(client, admin_headers, trip_id, monkeypatch)
    await _move(client, admin_headers, trip_id, "en_route")

    # No Authorization header: this is the whole point of the endpoint.
    res = await client.get(f"/api/track/{token}")
    assert res.status_code == 200, res.text
    body = res.json()

    assert body["org_name"] == "Test Org"
    assert body["plate"] == "10 990 NBA"
    assert body["origin"]["name"] == "Tobolsk"
    assert body["destination"]["name"] == "Tashkent"
    assert body["destination"]["latitude"] == 41.3
    assert body["cargo"] == "Polypropylene"


async def test_the_page_never_carries_the_rate(
    client: AsyncClient, admin_headers, monkeypatch
):
    """What the fleet is paid for the load is nobody else's business, and this
    response is fetchable by anyone holding the link."""
    _, trip_id = await _trip_with_truck(client, admin_headers)
    token = await _token_for(client, admin_headers, trip_id, monkeypatch)
    await _move(client, admin_headers, trip_id, "en_route")

    body = (await client.get(f"/api/track/{token}")).json()
    assert "rate" not in body
    assert "currency" not in body
    assert "driver_id" not in body
    assert "45000000" not in str(body)


async def test_a_truck_that_has_not_reported_yet_is_not_an_error(
    client: AsyncClient, admin_headers, monkeypatch
):
    """The page still renders the route and the reference; only the dot is
    missing, and "not known yet" is a real answer to "where is my cargo"."""
    _, trip_id = await _trip_with_truck(client, admin_headers)
    token = await _token_for(client, admin_headers, trip_id, monkeypatch)
    await _move(client, admin_headers, trip_id, "en_route")

    body = (await client.get(f"/api/track/{token}")).json()
    assert body["position"] is None
    assert body["reference"]


async def test_the_live_position_is_the_truck_s_latest(
    client: AsyncClient, admin_headers, monkeypatch
):
    truck_id, trip_id = await _trip_with_truck(client, admin_headers)
    token = await _token_for(client, admin_headers, trip_id, monkeypatch)
    await _move(client, admin_headers, trip_id, "en_route")

    imei = "352094081234567"
    device = (
        await client.post(
            "/api/devices",
            headers=admin_headers,
            json={"imei": imei, "truck_id": truck_id},
        )
    ).json()
    ping = await client.post(
        "/api/gps/ingest",
        headers={"X-API-Key": device["api_key"], "X-IMEI": imei},
        json={"points": [{"latitude": 43.21, "longitude": 68.9, "speed": 78}]},
    )
    assert ping.status_code == 200, ping.text

    body = (await client.get(f"/api/track/{token}")).json()
    assert body["position"]["latitude"] == 43.21
    assert body["position"]["longitude"] == 68.9
    assert body["position"]["speed"] == 78


async def test_an_unknown_token_is_a_404(client: AsyncClient):
    assert (await client.get("/api/track/not-a-real-token")).status_code == 404


async def test_a_delivered_trip_stops_being_watchable(
    client: AsyncClient, admin_headers, monkeypatch
):
    """The link was shared for one job. Leaving it live afterwards keeps the
    fleet's lorry on a stranger's screen long after the job ended."""
    _, trip_id = await _trip_with_truck(client, admin_headers)
    token = await _token_for(client, admin_headers, trip_id, monkeypatch)
    await _move(client, admin_headers, trip_id, "en_route")
    assert (await client.get(f"/api/track/{token}")).status_code == 200

    await _move(client, admin_headers, trip_id, "delivered")
    gone = await client.get(f"/api/track/{token}")
    assert gone.status_code == 404
    # Same wording as an unknown token: telling the two apart would confirm to
    # a guesser which of their guesses was a real subscription.
    assert gone.json() == (await client.get("/api/track/not-a-real-token")).json()


async def test_a_draft_trip_says_it_has_not_started_rather_than_expired(
    client: AsyncClient, admin_headers, monkeypatch
):
    """A dispatcher shares the link while the job is still being set up. Telling
    the customer the link "expired" sends them back for a new one that would
    fail the same way; saying the trip has not started tells them to wait."""
    _, trip_id = await _trip_with_truck(client, admin_headers)
    token = await _token_for(client, admin_headers, trip_id, monkeypatch)
    res = await client.get(f"/api/track/{token}")
    assert res.status_code == 409
    assert res.json()["detail"] == "not_started"


async def test_a_planned_trip_with_a_truck_is_watchable(
    client: AsyncClient, admin_headers, monkeypatch
):
    """Once a lorry is booked the customer wants to see it coming to load."""
    _, trip_id = await _trip_with_truck(client, admin_headers)
    token = await _token_for(client, admin_headers, trip_id, monkeypatch)
    await _move(client, admin_headers, trip_id, "planned")
    res = await client.get(f"/api/track/{token}")
    assert res.status_code == 200, res.text
    assert res.json()["plate"] == "10 990 NBA"


async def test_a_planned_trip_without_a_truck_has_not_started(
    client: AsyncClient, admin_headers, monkeypatch
):
    """No lorry means nothing to put on the map yet."""
    trip = (
        await client.post(
            "/api/trips",
            headers=admin_headers,
            json={"origin_name": "Tobolsk", "destination_name": "Tashkent"},
        )
    ).json()
    token = await _token_for(client, admin_headers, trip["id"], monkeypatch)
    await _move(client, admin_headers, trip["id"], "planned")
    res = await client.get(f"/api/track/{token}")
    assert res.status_code == 409
    assert res.json()["detail"] == "not_started"


# ── The link that gets a customer here ───────────────────────────────────


def test_the_track_url_is_built_off_the_web_app_s_address(monkeypatch):
    monkeypatch.setattr(settings, "public_web_url", "https://fleet.example/", raising=False)
    assert urls.track_url("abc123") == "https://fleet.example/track/abc123"


def test_no_web_address_means_no_link_rather_than_a_broken_one(monkeypatch):
    monkeypatch.setattr(settings, "public_web_url", "", raising=False)
    monkeypatch.setattr(settings, "cors_origins", "", raising=False)
    monkeypatch.delenv("PUBLIC_WEB_URL", raising=False)
    assert urls.track_url("abc123") is None


def test_no_token_means_no_link(monkeypatch):
    monkeypatch.setattr(settings, "public_web_url", "https://fleet.example", raising=False)
    assert urls.track_url(None) is None
    assert urls.track_url("") is None
