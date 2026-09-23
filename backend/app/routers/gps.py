"""GPS ingest — the hottest path in the application.

A twenty-truck fleet pinging every fifteen seconds is eighty requests a minute
here, and a tracker that loses signal in a tunnel flushes its buffer as one
batch of fifty positions when it comes back. Both shapes used to cost far more
than they look:

* every request re-verified the device's API key with bcrypt, synchronously,
  inside the event loop — ~200 ms during which nothing else in the process ran;
* every *point* re-selected its truck (twice), re-read every geofence, and
  re-queried the last event for each one, so a fifty-point batch against twenty
  fences issued upwards of a thousand queries;
* every point broadcast its own WebSocket frame, so a dispatcher watching the
  map received fifty updates of which forty-nine were already stale.

The handler below resolves each truck once, replays the batch against geofence
state held in memory, and sends one location frame per truck. Device
authentication moved to :mod:`app.services.device_auth`, which caches the
verification and keeps bcrypt off the loop.
"""
from datetime import datetime, timezone
from typing import Dict, List, Optional
import uuid

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rate_limit import limiter
from app.core.ws import ws_manager
from app.models.devices import Device
from app.models.trucks import Truck
from app.services.device_auth import verify_device_key
from app.services.gps import Position, record_positions
from app.services.geofences import evaluate_track

router = APIRouter(prefix="/api/gps", tags=["GPS"])


class GPSPoint(BaseModel):
    # truck_id is optional — an enrolled device assigned to a truck needs no
    # binding in the payload. Passing it explicitly still works, but it can
    # only ever name a truck inside the device's own organization.
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
) -> Device:
    """Resolve the enrolled device behind (IMEI, API key), or reject.

    There is no fleet-wide key any more. The global ``GPS_API_KEYS`` allow-list
    that used to back this up carried no organization of its own, so the tenant
    check further down — which compares the target truck against *the device's*
    org — had nothing to compare against and was skipped entirely: any holder of
    a global key could write a position onto any truck in any customer's fleet.
    A shared secret with no owner cannot be scoped after the fact, so it is gone
    rather than patched, and ``_check_secrets`` refuses to start a production
    process that still has one configured.
    """
    if not api_key:
        raise HTTPException(status_code=401, detail="Не передан API-ключ")
    if not imei:
        raise HTTPException(status_code=401, detail="Не передан IMEI")

    device = (
        await db.execute(select(Device).where(Device.imei == imei))
    ).scalar_one_or_none()
    if device is None or not await verify_device_key(imei, api_key, device.api_key_hash):
        # One message for both cases: which of the two was wrong is not the
        # caller's business, and telling them turns this into an IMEI oracle.
        raise HTTPException(status_code=401, detail="Неверный IMEI или API-ключ")
    return device


def _sort_key(point: GPSPoint) -> datetime:
    """Order a batch by the time the *device* recorded each fix.

    A tracker flushing a buffer does not promise payload order, and geofence
    replay reads the batch as a track: out-of-order points would report a truck
    leaving a depot before it arrived. Points with no timestamp sort last —
    they mean "now", which is later than anything the device timestamped.
    """
    recorded_at = point.recorded_at
    if recorded_at is None:
        return datetime.max.replace(tzinfo=timezone.utc)
    if recorded_at.tzinfo is None:
        return recorded_at.replace(tzinfo=timezone.utc)
    return recorded_at


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

    # Group first, query second. A batch is usually many points for one truck.
    by_truck: Dict[uuid.UUID, List[GPSPoint]] = {}
    for p in data.points:
        truck_id = p.truck_id or device.truck_id
        if truck_id is None:
            continue  # no truck binding — nothing to attach the point to
        by_truck.setdefault(truck_id, []).append(p)

    updated = 0
    if by_truck:
        # Tenant isolation lives in this WHERE clause: a truck_id belonging to
        # another organization simply does not come back, so the loop below
        # never sees it. One query for the whole batch.
        trucks = (
            await db.execute(
                select(Truck).where(
                    Truck.id.in_(list(by_truck)),
                    Truck.org_id == device.org_id,
                )
            )
        ).scalars().all()

        for truck in trucks:
            points = sorted(by_truck[truck.id], key=_sort_key)
            org_id = str(truck.org_id)

            updated += await record_positions(
                db,
                truck.id,
                [
                    Position(
                        latitude=p.latitude,
                        longitude=p.longitude,
                        speed=p.speed,
                        heading=p.heading,
                        address=p.address,
                        recorded_at=p.recorded_at,
                    )
                    for p in points
                ],
                truck=truck,
            )

            # One frame per truck. The map draws a position, not a history —
            # the intermediate points are already durable in the history table
            # and the analytics that care read them from there.
            latest = points[-1]
            await ws_manager.broadcast_to_org(org_id, {
                "type": "truck_location_update",
                "truck_id": str(truck.id),
                "lat": latest.latitude,
                "lng": latest.longitude,
                "speed": latest.speed,
                "heading": latest.heading,
                "recorded_at": (latest.recorded_at.isoformat() if latest.recorded_at else None),
            })

            # Geofence crossings, on the other hand, are events: a truck that
            # entered and left a depot inside one buffered batch did both, and
            # collapsing that to its last position would lose the visit.
            events = await evaluate_track(
                db=db,
                truck_id=truck.id,
                points=[(p.latitude, p.longitude, p.recorded_at) for p in points],
                org_id=truck.org_id,
            )
            for ev in events:
                await ws_manager.broadcast_to_org(org_id, {
                    "type": "geofence_event",
                    "truck_id": str(truck.id),
                    "geofence_id": str(ev.geofence_id),
                    "event": ev.event.value,
                    "lat": float(ev.latitude),
                    "lng": float(ev.longitude),
                    "recorded_at": ev.recorded_at.isoformat(),
                })

    device.last_seen_at = datetime.now(timezone.utc)

    await db.commit()
    return {"message": "ingested", "updated": updated}
