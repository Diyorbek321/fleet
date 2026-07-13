"""Send Telegram notifications when a trip's status changes.

Called from both dispatcher-side (``/api/trips/{id}/advance``) and driver-side
(``/api/me/trips/{id}/advance``) after the commit that stored the new status,
so the cargo owner learns "yuk chegaraga yetdi" in real time regardless of
who moved the trip through the timeline.

Best-effort: any failure (missing subscription, blocked bot, Telegram
outage) is logged and swallowed. Trip advancement must never fail because
notifications can't be delivered.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.logging import logger
from app.models.enums import TripStatus
from app.models.notifications import TripSubscription
from app.models.trips import Trip
from app.services.telegram import format_status_change, send_message


async def notify_trip_status_change(
    db: AsyncSession,
    trip: Trip,
    to_status: TripStatus,
    latitude: float | None = None,
    longitude: float | None = None,
    note: str | None = None,
) -> int:
    """Push a status-change message to every activated subscriber of the trip.

    Returns the number of successful sends. Callers can ignore the return —
    it's only useful for tests and structured logging.
    """
    if not settings.telegram_configured:
        return 0

    try:
        subs = (
            await db.execute(
                select(TripSubscription).where(
                    TripSubscription.trip_id == trip.id,
                    TripSubscription.chat_id.is_not(None),
                    TripSubscription.event_enabled.is_(True),
                )
            )
        ).scalars().all()
    except Exception:  # noqa: BLE001
        logger.exception("trip_notify_lookup_failed", trip_id=str(trip.id))
        return 0

    if not subs:
        return 0

    text = format_status_change(
        trip.reference,
        to_status,
        float(latitude) if latitude is not None else None,
        float(longitude) if longitude is not None else None,
        note,
    )

    sent = 0
    for sub in subs:
        # chat_id is guaranteed non-null by the query, but keep the guard
        # so the type checker is happy.
        if not sub.chat_id:
            continue
        result = await send_message(sub.chat_id, text)
        if result.ok:
            sent += 1
        elif result.permanently_failed:
            # Chat is dead — disable so tomorrow's batch doesn't retry.
            sub.event_enabled = False
            sub.daily_enabled = False

    try:
        await db.commit()
    except Exception:  # noqa: BLE001
        await db.rollback()
        logger.exception("trip_notify_flag_update_failed", trip_id=str(trip.id))

    logger.info(
        "trip_notify_status_change",
        trip_id=str(trip.id),
        to_status=to_status.value,
        subscribers=len(subs),
        sent=sent,
    )
    return sent


async def notify_trip_status_change_background(
    trip_id: uuid.UUID,
    to_status: TripStatus,
    latitude: float | None,
    longitude: float | None,
    note: str | None,
) -> None:
    """FastAPI ``BackgroundTasks`` entrypoint — runs after the response is sent.

    The request-scoped session is already closed by then, so this opens its
    own short-lived session (same pattern as the scheduler in
    ``daily_updates.py``). Lets ``advance_trip`` return to the dispatcher
    immediately instead of blocking on Telegram delivery.
    """
    try:
        async with SessionLocal() as db:
            trip = (await db.execute(select(Trip).where(Trip.id == trip_id))).scalar_one_or_none()
            if trip is None:
                return
            await notify_trip_status_change(db, trip, to_status, latitude, longitude, note)
    except Exception:  # noqa: BLE001 — background task, nothing to propagate to
        logger.exception("trip_notify_background_failed", trip_id=str(trip_id))
