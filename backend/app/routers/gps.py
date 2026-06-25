from datetime import datetime, timezone
from typing import List, Optional
import uuid

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.rate_limit import limiter
from app.core.security import verify_password
from app.core.ws import ws_manager
from app.models.devices import Device
from app.models.trucks import Truck
from app.services.gps import upsert_latest_location
from app.services.geofences import evaluate_geofences

router = APIRouter(prefix="/api/gps", tags=["GPS"])


class GPSPoint(BaseModel):
    # truck_id is now optional — if the device is enrolled and assigned to a
    # truck, we use that binding. A fleet operator can still override by
    # passing truck_id explicitly (useful for testing).
    truck_id: Optional[uuid.UUID] = None
    latitude: float
    longitude: float
    speed: float = 0
    heading: Optional[float] = None
    address: Optional[str] = None
    recorded_at: Optional[datetime] = None


class GPSIngestIn(BaseModel):
    points: List[GPSPoint] = Field(default_factory=list, min_length=1)


async def _authenticate_device(
    db: AsyncSession,
    imei: Optional[str],
    api_key: Optional[str],
) -> Optional[Device]:
    """Per-device authentication. Returns the Device if (imei, api_key) match.

    Falls back to the global `GPS_API_KEYS` allow-list in settings for
    backwards compatibility with pre-device-enrollment setups.
    """
    if not api_key:
        raise HTTPException(status_code=401, detail="Missing API key")

    if imei:
        device = (await db.execute(select(Device).where(Device.imei == imei))).scalar_one_or_none()
        if device and verify_password(api_key, device.api_key_hash):
            return device

    # Legacy fallback: global fleet-wide API keys from .env
    if api_key in settings.gps_keys_set():
        return None

    raise HTTPException(status_code=401, detail="Invalid IMEI or API key")


@router.post("/ingest")
@limiter.limit("600/minute")  # 10 points/sec per source IP — generous for a fleet gateway
async def ingest(
    request: Request,
    data: GPSIngestIn = Body(...),
    db: AsyncSession = Depends(get_db),
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    x_imei: Optional[str] = Header(default=None, alias="X-IMEI"),
):
    device = await _authenticate_device(db, x_imei, x_api_key)

    updated = 0
    for p in data.points:
        # Resolve truck: explicit point.truck_id beats device binding
        truck_id = p.truck_id or (device.truck_id if device else None)
        if not truck_id:
            continue  # no truck binding — ignore point

        truck = (await db.execute(select(Truck).where(Truck.id == truck_id))).scalar_one_or_none()
        if not truck:
            continue

        # Tenant isolation: an enrolled device may only push to trucks in its own
        # organization, even if it tries to spoof another org's truck_id.
        if device is not None and truck.org_id != device.org_id:
            continue

        org_id = str(truck.org_id)

        await upsert_latest_location(
            db=db,
            truck_id=truck_id,
            latitude=p.latitude,
            longitude=p.longitude,
            speed=p.speed,
            heading=p.heading,
            address=p.address,
            recorded_at=p.recorded_at,
        )
        updated += 1

        await ws_manager.broadcast_to_org(org_id, {
            "type": "truck_location_update",
            "truck_id": str(truck_id),
            "lat": p.latitude,
            "lng": p.longitude,
            "speed": p.speed,
            "heading": p.heading,
            "recorded_at": (p.recorded_at.isoformat() if p.recorded_at else None),
        })

        # Geofence enter/exit detection — broadcast any boundary crossings
        events = await evaluate_geofences(
            db=db,
            truck_id=truck_id,
            latitude=p.latitude,
            longitude=p.longitude,
            recorded_at=p.recorded_at,
            org_id=truck.org_id,
        )
        for ev in events:
            await ws_manager.broadcast_to_org(org_id, {
                "type": "geofence_event",
                "truck_id": str(truck_id),
                "geofence_id": str(ev.geofence_id),
                "event": ev.event.value,
                "lat": p.latitude,
                "lng": p.longitude,
                "recorded_at": ev.recorded_at.isoformat(),
            })

    if device:
        device.last_seen_at = datetime.now(timezone.utc)

    await db.commit()
    return {"message": "ingested", "updated": updated}
