"""Wake a driver's phone that has gone quiet.

Android stops a backgrounded app's location service on its own schedule —
battery savers, a maker's task killer, an OS update. The phone is still on
and online; it has just stopped reporting. A data-only, high-priority FCM
message is the one thing Android lets restart it: nothing is shown, the app's
background task runs and switches tracking back on (see the app's
``wake-task.ts``).

Only for phones that were reporting recently. A phone silent for days is off,
lost or out of network; pushing it every tick would change nothing, and the
driver and dispatcher reminders cover it.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import logger
from app.models.trucks import Truck
from app.services import push
from app.services.driver_messages import driver_tokens
from app.services.truck_signal import SignalState, fleet_signal

__all__ = ["run", "WAKE_FOR"]

# Past this, the silence is not something a wake-up can fix.
WAKE_FOR = timedelta(days=2)


async def run(db: AsyncSession) -> int:
    """Wake every recently silent phone. Returns how many drivers were pushed."""
    now = datetime.now(timezone.utc)
    stale = timedelta(minutes=settings.gps_stale_after_minutes)
    org_ids = (
        await db.execute(select(Truck.org_id).where(Truck.is_enabled.is_(True)).distinct())
    ).scalars().all()

    woken = 0
    for org_id in org_ids:
        try:
            for signal in await fleet_signal(db, org_id, stale, now=now):
                if (
                    signal.state is not SignalState.silent
                    or signal.driver_id is None
                    or signal.last_fix_at is None
                    or now - signal.last_fix_at > WAKE_FOR
                ):
                    continue
                tokens = await driver_tokens(db, signal.driver_id)
                if not tokens:
                    continue
                await push.send_to_tokens(
                    db, tokens, title="", body="", data={"kind": "wake"}, silent=True
                )
                woken += 1
            await db.commit()  # dead tokens removed by the sender
        except Exception:  # noqa: BLE001 — one fleet must not stop the others.
            logger.exception("phone_wake_org_failed", org_id=str(org_id))
            await db.rollback()
    logger.info("phone_wake_done", woken=woken)
    return woken
