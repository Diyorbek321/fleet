"""Filling the ``address`` column the live map has been rendering as "—".

What matters here is not that a label appears. It is that a geocoder having a
bad minute never *removes* one that is already on the screen, and that one tick
cannot run long enough to collide with the next.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.trucks import TruckLocation
from app.services import geocoding, location_labels
from app.services.location_labels import MAX_LOOKUPS_PER_RUN, refresh_location_addresses


@pytest.fixture(autouse=True)
def _geocoding_on(monkeypatch):
    monkeypatch.setattr(settings, "geocoding_enabled", True, raising=False)
    yield


async def _truck_with_fix(
    client: AsyncClient,
    headers: dict,
    db: AsyncSession,
    *,
    plate: str,
    lat: float = 41.0167,
    lng: float = 70.1436,
    address: str | None = None,
    recorded_at: datetime | None = None,
) -> uuid.UUID:
    res = await client.post(
        "/api/trucks", headers=headers, json={"name": plate, "plate_number": plate}
    )
    truck_id = uuid.UUID(res.json()["id"])
    db.add(
        TruckLocation(
            truck_id=truck_id,
            latitude=lat,
            longitude=lng,
            speed=0,
            address=address,
            recorded_at=recorded_at or datetime.now(timezone.utc),
        )
    )
    await db.commit()
    return truck_id


async def _address_of(db: AsyncSession, truck_id: uuid.UUID) -> str | None:
    row = (
        await db.execute(select(TruckLocation).where(TruckLocation.truck_id == truck_id))
    ).scalar_one()
    await db.refresh(row)
    return row.address


async def test_a_blank_position_gets_a_place_name(
    client: AsyncClient, admin_headers, db: AsyncSession, monkeypatch
):
    truck_id = await _truck_with_fix(client, admin_headers, db, plate="LBL-01")

    async def fake_describe(lat, lng, **kw):
        return "Казахстан, Sariog'ash"

    monkeypatch.setattr(geocoding, "describe", fake_describe)

    assert await refresh_location_addresses(db) == 1
    assert await _address_of(db, truck_id) == "Казахстан, Sariog'ash"


async def test_an_unknown_place_does_not_erase_the_label_on_screen(
    client: AsyncClient, admin_headers, db: AsyncSession, monkeypatch
):
    """The geocoder blinking must not blank a cell the dispatcher was reading."""
    truck_id = await _truck_with_fix(
        client, admin_headers, db, plate="LBL-02", address="Узбекистан, Angren"
    )

    async def fake_describe(lat, lng, **kw):
        return None

    monkeypatch.setattr(geocoding, "describe", fake_describe)

    assert await refresh_location_addresses(db) == 0
    assert await _address_of(db, truck_id) == "Узбекистан, Angren"


async def test_an_unchanged_place_is_not_rewritten(
    client: AsyncClient, admin_headers, db: AsyncSession, monkeypatch
):
    await _truck_with_fix(
        client, admin_headers, db, plate="LBL-03", address="Узбекистан, Angren"
    )

    async def fake_describe(lat, lng, **kw):
        return "Узбекистан, Angren"

    monkeypatch.setattr(geocoding, "describe", fake_describe)

    assert await refresh_location_addresses(db) == 0


async def test_a_truck_that_moved_gets_relabelled(
    client: AsyncClient, admin_headers, db: AsyncSession, monkeypatch
):
    truck_id = await _truck_with_fix(
        client, admin_headers, db, plate="LBL-04", address="Узбекистан, Angren"
    )

    async def fake_describe(lat, lng, **kw):
        return "Казахстан, Sariog'ash"

    monkeypatch.setattr(geocoding, "describe", fake_describe)

    assert await refresh_location_addresses(db) == 1
    assert await _address_of(db, truck_id) == "Казахстан, Sariog'ash"


async def test_unlabelled_trucks_are_served_before_already_labelled_ones(
    client: AsyncClient, admin_headers, db: AsyncSession, monkeypatch
):
    """The cap is what makes ordering matter: whoever is cut off waits a tick,
    and a blank cell is worse to look at than a slightly stale one."""
    older = datetime.now(timezone.utc) - timedelta(hours=3)
    await _truck_with_fix(
        client, admin_headers, db, plate="LBL-05", address="Eski nom", recorded_at=None
    )
    blank_id = await _truck_with_fix(
        client, admin_headers, db, plate="LBL-06", address=None, recorded_at=older
    )

    seen: list[tuple[float, float]] = []

    async def fake_describe(lat, lng, **kw):
        seen.append((lat, lng))
        return "Казахстан, Sariog'ash"

    monkeypatch.setattr(geocoding, "describe", fake_describe)
    monkeypatch.setattr(location_labels, "MAX_LOOKUPS_PER_RUN", 1)

    await refresh_location_addresses(db)

    assert len(seen) == 1
    assert await _address_of(db, blank_id) == "Казахстан, Sariog'ash"


async def test_one_tick_never_exceeds_the_lookup_cap(
    client: AsyncClient, admin_headers, db: AsyncSession, monkeypatch
):
    for i in range(4):
        await _truck_with_fix(client, admin_headers, db, plate=f"CAP-{i:02d}")

    calls: list[int] = []

    async def fake_describe(lat, lng, **kw):
        calls.append(1)
        return "Казахстан"

    monkeypatch.setattr(geocoding, "describe", fake_describe)
    monkeypatch.setattr(location_labels, "MAX_LOOKUPS_PER_RUN", 2)

    await refresh_location_addresses(db)
    assert len(calls) == 2


async def test_disabled_geocoding_touches_nothing(
    client: AsyncClient, admin_headers, db: AsyncSession, monkeypatch
):
    truck_id = await _truck_with_fix(client, admin_headers, db, plate="LBL-07")
    monkeypatch.setattr(settings, "geocoding_enabled", False, raising=False)

    async def explode(lat, lng, **kw):  # pragma: no cover - must never run
        raise AssertionError("geocoder called while the feature is off")

    monkeypatch.setattr(geocoding, "describe", explode)

    assert await refresh_location_addresses(db) == 0
    assert await _address_of(db, truck_id) is None


async def test_the_label_reaches_the_live_map_endpoint(
    client: AsyncClient, admin_headers, db: AsyncSession, monkeypatch
):
    """End of the chain: what the job writes is what the map reads."""
    await _truck_with_fix(client, admin_headers, db, plate="LBL-08")

    async def fake_describe(lat, lng, **kw):
        return "Казахстан, Sariog'ash"

    monkeypatch.setattr(geocoding, "describe", fake_describe)
    await refresh_location_addresses(db)

    res = await client.get("/api/trucks/locations", headers=admin_headers)
    assert res.status_code == 200
    addresses = [row["address"] for row in res.json()]
    assert "Казахстан, Sariog'ash" in addresses
