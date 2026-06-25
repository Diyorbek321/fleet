from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from app.models.trucks import Truck, TruckLocation, TruckLocationHistory
from app.models.enums import TruckStatus

def status_from_speed(speed_kmh: float) -> TruckStatus:
    # You can tune thresholds:
    if speed_kmh is None:
        return TruckStatus.offline
    if speed_kmh >= 5:
        return TruckStatus.moving
    if 0.5 <= speed_kmh < 5:
        return TruckStatus.idle
    return TruckStatus.stopped

async def upsert_latest_location(
    db: AsyncSession,
    truck_id,
    latitude: float,
    longitude: float,
    speed: float = 0,
    heading: Optional[float] = None,
    address: Optional[str] = None,
    recorded_at: Optional[datetime] = None,
) -> None:
    recorded_at = recorded_at or datetime.now(timezone.utc)

    # Upsert (insert on conflict truck_id)
    stmt = insert(TruckLocation).values(
        truck_id=truck_id,
        latitude=latitude,
        longitude=longitude,
        speed=speed or 0,
        heading=heading,
        address=address,
        recorded_at=recorded_at,
    ).on_conflict_do_update(
        index_elements=["truck_id"],
        set_={
            "latitude": latitude,
            "longitude": longitude,
            "speed": speed or 0,
            "heading": heading,
            "address": address,
            "recorded_at": recorded_at,
        },
    )
    await db.execute(stmt)

    # History insert
    db.add(TruckLocationHistory(
        truck_id=truck_id,
        latitude=latitude,
        longitude=longitude,
        speed=speed,
        heading=heading,
        recorded_at=recorded_at,
    ))

    # Update truck status
    res = await db.execute(select(Truck).where(Truck.id == truck_id))
    truck = res.scalar_one_or_none()
    if truck:
        truck.status = status_from_speed(float(speed or 0))
        truck.updated_at = datetime.now(timezone.utc)
