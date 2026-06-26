"""Queue-watch evaluation: check a driver's CarGoRuqsat booking and decide whether
to notify. Kept independent of HTTP and FastAPI so it is straightforward to test and
to drive from a background scheduler later.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger
from app.models.driver_app import PushToken, QueueWatch
from app.models.users import User
from app.services.cgr import BookingRecord, CgrClient

# Status string stored when the truck has no booking in the public registry.
NO_BOOKING = "none"


async def evaluate_watch(
    watch: QueueWatch, client: CgrClient
) -> tuple[Optional[BookingRecord], bool]:
    """Refresh a watch against the public registry.

    Mutates the watch's ``last_status`` / ``last_seen_queue_at`` and returns the
    looked-up record plus whether the status changed since the last *notification*.
    """
    record = await client.lookup_truck(watch.plate)
    new_status = record.status.value if record else NO_BOOKING

    notify = new_status != (watch.last_notified_status or NO_BOOKING)

    watch.last_status = new_status
    if record and record.queue_at is not None:
        watch.last_seen_queue_at = record.queue_at
    watch.updated_at = datetime.now(timezone.utc)

    return record, notify


async def notify_queue_change(
    db: AsyncSession, watch: QueueWatch, record: Optional[BookingRecord]
) -> int:
    """Record that we've notified the driver of the current status and fan out to
    their registered devices. Returns the number of target devices.

    NOTE: actual push delivery (Expo/FCM/APNs) is a separate integration; here we
    resolve the devices and mark the watch so we don't re-notify the same status.
    """
    watch.last_notified_status = watch.last_status

    user = (
        await db.execute(select(User).where(User.driver_id == watch.driver_id))
    ).scalar_one_or_none()
    if user is None:
        return 0

    tokens = (
        await db.execute(select(PushToken).where(PushToken.user_id == user.id))
    ).scalars().all()

    logger.info(
        "queue_watch_notify",
        extra={
            "driver_id": str(watch.driver_id),
            "plate": watch.plate,
            "status": watch.last_status,
            "devices": len(tokens),
        },
    )
    return len(tokens)


async def poll_active_watches(db: AsyncSession, client: CgrClient) -> int:
    """Refresh every active queue-watch (across all orgs) and notify on change.

    Designed to be driven from the background scheduler. Each watch is evaluated
    in isolation so one failing external lookup never aborts the whole batch; we
    commit once at the end. Returns the number of watches whose status changed.
    """
    watches = (
        await db.execute(select(QueueWatch).where(QueueWatch.active.is_(True)))
    ).scalars().all()

    changed = 0
    for watch in watches:
        try:
            record, notify = await evaluate_watch(watch, client)
            if notify:
                await notify_queue_change(db, watch, record)
                changed += 1
        except Exception:  # noqa: BLE001 — one bad lookup must not abort the batch
            logger.exception(
                "queue_watch_poll_failed",
                extra={"watch_id": str(watch.id), "plate": watch.plate},
            )

    await db.commit()
    return changed
