"""Who I am, what I drive, when I'm on the clock, and where I am."""
from __future__ import annotations
import uuid

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlalchemy import delete, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.ws import ws_manager
from app.deps.auth import get_current_driver, get_current_user
from app.models.driver_app import PushToken, Shift
from app.models.drivers import Driver, SafetyScore
from app.models.trucks import Truck, TruckLocationHistory
from app.models.enums import ShiftStatus
from app.models.users import User
from app.routers.me._common import PREFIX, TAGS, assigned_truck, require_assigned_truck
from app.schemas.drivers import DriverOut, SafetyScoreOut
from app.schemas.me import (
    AssignedTruckOut,
    LocationBatchIn,
    LocationPingIn,
    LocationPointIn,
    PhoneStateIn,
    PushTokenIn,
    ShiftEndIn,
    ShiftOut,
    ShiftStartIn,
)
from app.services.geofences import evaluate_track
from app.services.gps import Position, record_positions

router = APIRouter(prefix=PREFIX, tags=TAGS)

# The driver app reports ``coords.speed`` straight from expo-location, which is
# metres per second; everything downstream (status thresholds, trip segments,
# the Telegram "Скорость: N км/ч" line) works in km/h. Converting here rather
# than in the app fixes every phone already installed without a new APK.
MPS_TO_KMH = 3.6


def _phone_speed_kmh(speed_mps: float) -> float:
    # iOS reports -1 when it has no speed estimate; that is "unknown", not reverse.
    return max(0.0, speed_mps) * MPS_TO_KMH


# ── Profile & assignment ──────────────────────────────────────────────

@router.get("/profile", response_model=DriverOut)
async def my_profile(driver: Driver = Depends(get_current_driver)):
    return driver


@router.get("/assignment", response_model=Optional[AssignedTruckOut])
async def my_assignment(
    driver: Driver = Depends(get_current_driver),
    db: AsyncSession = Depends(get_db),
):
    """The truck assigned to me right now, or null if none."""
    return await assigned_truck(db, driver.id)


@router.get("/safety-score", response_model=Optional[SafetyScoreOut])
async def my_safety_score(
    driver: Driver = Depends(get_current_driver),
    db: AsyncSession = Depends(get_db),
):
    res = await db.execute(
        select(SafetyScore)
        .where(SafetyScore.driver_id == driver.id)
        .order_by(desc(SafetyScore.calculated_at))
    )
    return res.scalars().first()


# ── Shifts (clock in / out) ───────────────────────────────────────────

@router.get("/shifts/current", response_model=Optional[ShiftOut])
async def current_shift(
    driver: Driver = Depends(get_current_driver),
    db: AsyncSession = Depends(get_db),
):
    res = await db.execute(
        select(Shift)
        .where(Shift.driver_id == driver.id, Shift.status == ShiftStatus.active)
        .order_by(desc(Shift.started_at))
    )
    return res.scalars().first()


@router.post("/shifts/start", response_model=ShiftOut, status_code=status.HTTP_201_CREATED)
async def start_shift(
    data: ShiftStartIn = Body(default_factory=ShiftStartIn),
    driver: Driver = Depends(get_current_driver),
    db: AsyncSession = Depends(get_db),
):
    existing = await db.execute(
        select(Shift).where(Shift.driver_id == driver.id, Shift.status == ShiftStatus.active)
    )
    if existing.scalars().first():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Смена уже открыта")

    truck = await assigned_truck(db, driver.id)
    shift = Shift(
        driver_id=driver.id,
        truck_id=truck.id if truck else None,
        start_mileage=data.start_mileage,
    )
    db.add(shift)
    await db.commit()
    await db.refresh(shift)
    return shift


@router.post("/shifts/end", response_model=ShiftOut)
async def end_shift(
    data: ShiftEndIn = Body(default_factory=ShiftEndIn),
    driver: Driver = Depends(get_current_driver),
    db: AsyncSession = Depends(get_db),
):
    res = await db.execute(
        select(Shift)
        .where(Shift.driver_id == driver.id, Shift.status == ShiftStatus.active)
        .order_by(desc(Shift.started_at))
    )
    shift = res.scalars().first()
    if shift is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Нет открытой смены")

    shift.status = ShiftStatus.ended
    shift.ended_at = datetime.now(timezone.utc)
    shift.end_mileage = data.end_mileage
    await db.commit()
    await db.refresh(shift)
    return shift


# ── Live location (phone-as-tracker) ──────────────────────────────────

def _aware(moment: datetime | None) -> datetime | None:
    """A timestamp sent without a zone is UTC, so it can sort against "now"."""
    if moment is not None and moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment


# Drift below this is network latency and a phone a little off; above it the
# phone's clock is wrong (set by hand, or a SIM that never synced it).
CLOCK_TOLERANCE = timedelta(minutes=2)


def _on_server_clock(
    points: list[LocationPointIn], sent_at: datetime | None, now: datetime
) -> list[LocationPointIn]:
    """Fix timestamps the way the server's clock would have written them.

    The phone stamps each fix with its own clock. Hours ahead, its fixes sat in
    the future and the current position — which only moves forward — froze on
    them; hours behind, a live truck read as silent. ``sent_at`` is that same
    clock at send time, so the gap to the server's clock is the error in every
    stamp. Whatever remains in the future afterwards is capped at now, which
    also covers clients that do not send ``sent_at``.
    """
    skew = timedelta(0)
    sent = _aware(sent_at)
    if sent is not None and abs(sent - now) > CLOCK_TOLERANCE:
        # Whole minutes: a retry measures it a few seconds differently, and
        # the same fix must land on the same time or the dedupe misses it.
        skew = timedelta(minutes=round((sent - now).total_seconds() / 60))

    def fixed(p: LocationPointIn) -> LocationPointIn:
        at = _aware(p.recorded_at)
        if at is None:
            return p
        return p.model_copy(update={"recorded_at": min(at - skew, now)})

    return [fixed(p) for p in points]


async def _not_yet_recorded(
    db: AsyncSession, truck_id: uuid.UUID, points: list[LocationPointIn]
) -> list[LocationPointIn]:
    """Drop fixes already in the history.

    A phone whose request reached the server but whose answer was lost sends
    the same buffer again; without this every such retry doubled a stretch of
    the track.
    """
    stamps = [_aware(p.recorded_at) for p in points if p.recorded_at is not None]
    if not stamps:
        return points
    seen = set(
        (
            await db.execute(
                select(TruckLocationHistory.recorded_at).where(
                    TruckLocationHistory.truck_id == truck_id,
                    TruckLocationHistory.recorded_at.in_(stamps),
                )
            )
        ).scalars()
    )
    return [p for p in points if p.recorded_at is None or _aware(p.recorded_at) not in seen]


def _record_phone_state(truck: Truck, state: PhoneStateIn) -> None:
    """Keep what the phone said about itself. Fields it did not send keep their
    last value: an older APK sends none, and must not erase a newer one's."""
    sent = state.model_dump(include={"battery", "tracking", "app_version"}, exclude_none=True)
    if not sent:
        return
    if "battery" in sent:
        truck.phone_battery = sent["battery"]
    if "tracking" in sent:
        truck.phone_tracking = sent["tracking"]
    if "app_version" in sent:
        truck.phone_app_version = sent["app_version"]
    truck.phone_reported_at = datetime.now(timezone.utc)


async def _ingest(
    db: AsyncSession, driver: Driver, points: list[LocationPointIn], state: PhoneStateIn
) -> dict:
    """The one path for a phone's fixes, whether one live ping or a buffer.

    This is the same pipeline as ``POST /api/gps/ingest``; only the credential
    differs. It evaluates geofences too — a truck is inside the depot or it is
    not, and which device happened to report the fix is not something the fence
    should care about. While this path skipped that step, a fleet running on
    phones instead of trackers had geofences that silently never fired.
    """
    truck = await require_assigned_truck(db, driver.id)
    now = datetime.now(timezone.utc)
    points = _on_server_clock(points, state.sent_at, now)
    # Oldest first, as record_positions expects; a buffer can arrive shuffled.
    ordered = sorted(points, key=lambda p: _aware(p.recorded_at) or now)
    ordered = await _not_yet_recorded(db, truck.id, ordered)
    if not ordered:
        return {"message": "ok", "truck_id": str(truck.id), "accepted": 0}
    positions = [
        Position(
            latitude=p.latitude,
            longitude=p.longitude,
            speed=_phone_speed_kmh(p.speed),
            heading=p.heading,
            recorded_at=p.recorded_at,
        )
        for p in ordered
    ]
    moved = (await record_positions(db, truck.id, positions, truck=truck)).moved
    _record_phone_state(truck, state)
    # Fences replay from their last recorded event, so only a batch that ends
    # at the truck's newest position can be replayed onto them. A buffer older
    # than that would be judged against where the truck is now and announce an
    # exit or entry that never happened; it fills in the history only.
    events = []
    if moved:
        events = await evaluate_track(
            db=db,
            truck_id=truck.id,
            points=[(p.latitude, p.longitude, p.recorded_at) for p in ordered],
            org_id=truck.org_id,
        )
    await db.commit()

    # Live map fan-out is scoped to the truck's organization — and only when the
    # truck actually moved on the map: a buffer older than the last live fix
    # fills in the history and leaves the marker where it is.
    org_id = str(truck.org_id)
    latest = positions[-1]
    if moved:
        await ws_manager.broadcast_to_org(org_id, {
            "type": "truck_location_update",
            "truck_id": str(truck.id),
            "lat": latest.latitude,
            "lng": latest.longitude,
            "speed": latest.speed,
            "heading": latest.heading,
            "recorded_at": (latest.recorded_at or now).isoformat(),
        })
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
    return {"message": "ok", "truck_id": str(truck.id), "accepted": len(positions)}


@router.post("/location")
async def ping_location(
    data: LocationPingIn = Body(...),
    driver: Driver = Depends(get_current_driver),
    db: AsyncSession = Depends(get_db),
):
    """Driver's phone streams its GPS position to their assigned truck."""
    return await _ingest(db, driver, [data], data)


@router.post("/locations")
async def ping_locations(
    data: LocationBatchIn = Body(...),
    driver: Driver = Depends(get_current_driver),
    db: AsyncSession = Depends(get_db),
):
    """Fixes the phone kept while it had no signal, sent in one request.

    Without this the Kazakh steppe was a straight line on the map: the phone
    had positions for every hour of it and nowhere to put them.
    """
    return await _ingest(db, driver, data.points, data)


# ── Push notification token registration ──────────────────────────────

@router.post("/push-token", status_code=status.HTTP_201_CREATED)
async def register_push_token(
    data: PushTokenIn = Body(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    existing = await db.execute(select(PushToken).where(PushToken.token == data.token))
    row = existing.scalar_one_or_none()
    if row:
        # Re-point rather than reject: a token follows the handset, so when a
        # second driver signs in on the same phone the old owner must stop
        # receiving that phone's notifications.
        row.user_id = user.id
        row.platform = data.platform
    else:
        db.add(PushToken(user_id=user.id, token=data.token, platform=data.platform))
    await db.commit()
    return {"message": "registered"}


@router.delete("/push-token", status_code=status.HTTP_200_OK)
async def unregister_push_token(
    data: PushTokenIn = Body(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Drop one device's registration, on sign-out.

    Scoped to the caller's own tokens: the token string is the only identifier
    the client holds, and without the ``user_id`` filter anyone holding (or
    guessing) another driver's token could silence their notifications.

    Deleting nothing is a success. The client calls this while tearing down its
    session and cannot act on a 404 — and the token may already be gone,
    dropped when Expo reported the device as unregistered.
    """
    await db.execute(
        delete(PushToken).where(
            PushToken.token == data.token,
            PushToken.user_id == user.id,
        )
    )
    await db.commit()
    return {"message": "unregistered"}
