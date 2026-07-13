"""Daily "where is my cargo" digest for Telegram subscribers.

Runs from the APScheduler tick — inside :func:`send_daily_trip_updates` we
gate execution to a specific hour of day (UTC) so calling the job every
15 minutes still fires the batch only once per morning. That's simpler and
safer than reconfiguring APScheduler with a cron trigger from a settings
value.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.logging import logger
from app.models.enums import TripStatus
from app.models.notifications import TripSubscription
from app.models.trips import Trip
from app.models.trucks import TruckLocation
from app.services.telegram import format_daily_update, send_message


# Trip states worth pushing about — a delivered trip has no more updates,
# a cancelled trip is dead, and a draft/planned trip hasn't moved yet.
_ACTIVE_TRIP_STATES = {TripStatus.loading, TripStatus.en_route, TripStatus.at_border}


async def _run_batch(db: AsyncSession) -> tuple[int, int]:
    """Send the digest to every activated subscription of an active trip.

    Returns (subscribers_considered, messages_sent).
    """
    subs = (
        await db.execute(
            select(TripSubscription).where(
                TripSubscription.chat_id.is_not(None),
                TripSubscription.daily_enabled.is_(True),
            )
        )
    ).scalars().all()

    if not subs:
        return (0, 0)

    # Pre-load the trips (+ their truck's latest location) in one pass to
    # avoid N+1 selects across the batch.
    trip_ids = {sub.trip_id for sub in subs}
    trips = (
        await db.execute(
            select(Trip)
            .options(selectinload(Trip.events))
            .where(Trip.id.in_(trip_ids))
        )
    ).scalars().all()
    trip_by_id = {t.id: t for t in trips}

    truck_ids = {t.truck_id for t in trips if t.truck_id is not None}
    locations: dict = {}
    if truck_ids:
        loc_rows = (
            await db.execute(
                select(TruckLocation).where(TruckLocation.truck_id.in_(truck_ids))
            )
        ).scalars().all()
        locations = {loc.truck_id: loc for loc in loc_rows}

    sent = 0
    now = datetime.now(timezone.utc)
    today = now.date()
    for sub in subs:
        trip = trip_by_id.get(sub.trip_id)
        if trip is None or trip.status not in _ACTIVE_TRIP_STATES:
            continue

        # The scheduler re-runs this job every ~15 minutes but the digest
        # should only go out once per subscriber per UTC day — skip anyone
        # already messaged today so we don't spam the same "where is my
        # cargo" text on every tick within the target hour.
        if sub.last_daily_at is not None and sub.last_daily_at.astimezone(timezone.utc).date() == today:
            continue

        loc = locations.get(trip.truck_id) if trip.truck_id else None
        lat = float(loc.latitude) if loc is not None else None
        lng = float(loc.longitude) if loc is not None else None
        speed = float(loc.speed) if (loc is not None and loc.speed is not None) else None
        updated_at = loc.recorded_at if loc is not None else None

        text = format_daily_update(
            trip_reference=trip.reference,
            status=trip.status,
            lat=lat,
            lng=lng,
            destination=trip.destination_name,
            speed_kmh=speed,
            updated_at=updated_at,
        )
        if not sub.chat_id:
            continue
        result = await send_message(sub.chat_id, text)
        if result.ok:
            sent += 1
            sub.last_daily_at = now
        elif result.permanently_failed:
            sub.daily_enabled = False
            sub.event_enabled = False

    try:
        await db.commit()
    except Exception:  # noqa: BLE001
        await db.rollback()
        logger.exception("daily_update_flag_commit_failed")

    return (len(subs), sent)


async def send_daily_trip_updates() -> None:
    """Scheduler entrypoint. Fires once when the current UTC hour matches
    :attr:`Settings.telegram_daily_hour` — the scheduler runs every N minutes,
    so we gate here instead of adding a cron trigger keyed to a settings value.
    """
    if not settings.telegram_configured:
        return

    now = datetime.now(timezone.utc)
    if now.hour != settings.telegram_daily_hour:
        return

    try:
        async with SessionLocal() as db:
            considered, sent = await _run_batch(db)
        logger.info(
            "daily_trip_updates_done",
            hour=now.hour,
            considered=considered,
            sent=sent,
        )
    except Exception:  # noqa: BLE001 — never let a job crash the scheduler
        logger.exception("daily_trip_updates_failed")
