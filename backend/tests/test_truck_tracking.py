"""What the dashboard says about a truck must match what the truck last said.

Three ways the live view used to drift from the truth, each found on the
Angren TEK pilot:

* the driver app reports speed in m/s (expo-location), and it was stored as
  km/h — 84 km/h on the road showed as 23;
* every ping wrote ``address = NULL`` over the place name the labelling job had
  just filled in, so the address column was blank almost all the time;
* nothing ever moved a truck out of "moving" when its pings stopped — one sat
  on the map as "moving, 23 km/h" three days after its phone went quiet.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import TruckStatus
from app.models.trucks import Truck, TruckLocation
from app.services.gps import upsert_latest_location
from app.services.truck_freshness import mark_silent_trucks_offline


async def _create_truck(client: AsyncClient, headers: dict, plate: str = "TT-01") -> str:
    res = await client.post(
        "/api/trucks", headers=headers, json={"name": f"Truck {plate}", "plate_number": plate}
    )
    assert res.status_code in (200, 201), res.text
    return res.json()["id"]


async def _assign(client: AsyncClient, headers: dict, driver_id: str, truck_id: str) -> None:
    res = await client.post(
        f"/api/drivers/{driver_id}/assign", headers=headers, json={"truck_id": truck_id}
    )
    assert res.status_code in (200, 201), res.text


# ── speed units ───────────────────────────────────────────────────────


async def test_phone_speed_is_stored_in_kmh(client: AsyncClient, admin_headers, driver_login):
    truck_id = await _create_truck(client, admin_headers)
    await _assign(client, admin_headers, driver_login["driver_id"], truck_id)

    # 10 m/s from the phone is 36 km/h on the road.
    res = await client.post(
        "/api/me/location",
        headers=driver_login["headers"],
        json={"latitude": 41.3, "longitude": 69.2, "speed": 10},
    )
    assert res.status_code == 200

    loc = (await client.get(f"/api/trucks/{truck_id}/location", headers=admin_headers)).json()
    assert abs(float(loc["speed"]) - 36.0) < 0.01


async def test_phone_walking_pace_is_not_moving(client: AsyncClient, admin_headers, driver_login):
    """1 m/s is GPS drift in a parked cab, not a truck under way."""
    truck_id = await _create_truck(client, admin_headers)
    await _assign(client, admin_headers, driver_login["driver_id"], truck_id)

    await client.post(
        "/api/me/location",
        headers=driver_login["headers"],
        json={"latitude": 41.3, "longitude": 69.2, "speed": 1},
    )

    truck = (await client.get(f"/api/trucks/{truck_id}", headers=admin_headers)).json()
    assert truck["status"] == "idle"  # 3.6 km/h, below the moving threshold


async def test_phone_unknown_speed_is_zero(client: AsyncClient, admin_headers, driver_login):
    """iOS reports -1 when it has no speed estimate."""
    truck_id = await _create_truck(client, admin_headers)
    await _assign(client, admin_headers, driver_login["driver_id"], truck_id)

    await client.post(
        "/api/me/location",
        headers=driver_login["headers"],
        json={"latitude": 41.3, "longitude": 69.2, "speed": -1},
    )

    loc = (await client.get(f"/api/trucks/{truck_id}/location", headers=admin_headers)).json()
    assert float(loc["speed"]) == 0


# ── address label survives pings ──────────────────────────────────────


async def test_ping_without_address_keeps_the_existing_label(
    client: AsyncClient, admin_headers, db: AsyncSession
):
    truck_id = uuid.UUID(await _create_truck(client, admin_headers))

    await upsert_latest_location(db, truck_id, 41.3, 69.2, speed=0, address="Узбекистан, Ангрен")
    await db.commit()
    await upsert_latest_location(db, truck_id, 41.31, 69.21, speed=0)
    await db.commit()

    row = (
        await db.execute(select(TruckLocation).where(TruckLocation.truck_id == truck_id))
    ).scalar_one()
    await db.refresh(row)
    assert row.address == "Узбекистан, Ангрен"
    assert abs(float(row.latitude) - 41.31) < 1e-6


async def test_ping_with_address_replaces_the_label(
    client: AsyncClient, admin_headers, db: AsyncSession
):
    truck_id = uuid.UUID(await _create_truck(client, admin_headers))

    await upsert_latest_location(db, truck_id, 41.3, 69.2, address="Old")
    await db.commit()
    await upsert_latest_location(db, truck_id, 41.3, 69.2, address="New")
    await db.commit()

    row = (
        await db.execute(select(TruckLocation).where(TruckLocation.truck_id == truck_id))
    ).scalar_one()
    await db.refresh(row)
    assert row.address == "New"


# ── silent trucks go offline ──────────────────────────────────────────


async def _truck_with_fix(
    client: AsyncClient, headers: dict, db: AsyncSession, plate: str,
    *, age: timedelta, speed: float,
) -> uuid.UUID:
    truck_id = uuid.UUID(await _create_truck(client, headers, plate))
    await upsert_latest_location(
        db, truck_id, 41.3, 69.2, speed=speed,
        recorded_at=datetime.now(timezone.utc) - age,
    )
    await db.commit()
    return truck_id


async def _status(db: AsyncSession, truck_id: uuid.UUID) -> TruckStatus:
    truck = (await db.execute(select(Truck).where(Truck.id == truck_id))).scalar_one()
    await db.refresh(truck)
    return truck.status


async def test_silent_moving_truck_goes_offline(
    client: AsyncClient, admin_headers, db: AsyncSession
):
    truck_id = await _truck_with_fix(
        client, admin_headers, db, "SIL-01", age=timedelta(hours=3), speed=80
    )
    assert await _status(db, truck_id) == TruckStatus.moving

    changed = await mark_silent_trucks_offline(db, silent_after=timedelta(hours=2))

    assert changed == 1
    assert await _status(db, truck_id) == TruckStatus.offline


async def test_recent_fix_keeps_its_status(
    client: AsyncClient, admin_headers, db: AsyncSession
):
    moving = await _truck_with_fix(
        client, admin_headers, db, "LIVE-01", age=timedelta(minutes=10), speed=80
    )
    parked = await _truck_with_fix(
        client, admin_headers, db, "LIVE-02", age=timedelta(minutes=90), speed=0
    )

    assert await mark_silent_trucks_offline(db, silent_after=timedelta(hours=2)) == 0
    assert await _status(db, moving) == TruckStatus.moving
    assert await _status(db, parked) == TruckStatus.stopped


async def test_maintenance_is_left_alone(
    client: AsyncClient, admin_headers, db: AsyncSession
):
    """A truck in the workshop is not reporting on purpose — that is not 'offline'."""
    truck_id = await _truck_with_fix(
        client, admin_headers, db, "WS-01", age=timedelta(days=2), speed=0
    )
    await db.execute(
        update(Truck).where(Truck.id == truck_id).values(status=TruckStatus.maintenance)
    )
    await db.commit()

    assert await mark_silent_trucks_offline(db, silent_after=timedelta(hours=2)) == 0
    assert await _status(db, truck_id) == TruckStatus.maintenance


async def test_marking_offline_is_idempotent(
    client: AsyncClient, admin_headers, db: AsyncSession
):
    await _truck_with_fix(client, admin_headers, db, "IDEM-01", age=timedelta(hours=5), speed=0)

    assert await mark_silent_trucks_offline(db, silent_after=timedelta(hours=2)) == 1
    assert await mark_silent_trucks_offline(db, silent_after=timedelta(hours=2)) == 0


async def test_fresh_ping_brings_an_offline_truck_back(
    client: AsyncClient, admin_headers, db: AsyncSession
):
    truck_id = await _truck_with_fix(
        client, admin_headers, db, "BACK-01", age=timedelta(hours=5), speed=0
    )
    await mark_silent_trucks_offline(db, silent_after=timedelta(hours=2))
    assert await _status(db, truck_id) == TruckStatus.offline

    await upsert_latest_location(db, truck_id, 41.3, 69.2, speed=60)
    await db.commit()

    assert await _status(db, truck_id) == TruckStatus.moving
