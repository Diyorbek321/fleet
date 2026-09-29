"""Stop showing a truck's last known status as if it were live.

``trucks.status`` is only ever written when a position arrives
(:func:`app.services.gps.record_positions`). When a phone dies, loses signal
past the border, or the driver logs out, the pings stop — and the badge stays
exactly where the last one left it. On the Angren TEK pilot a truck sat on the
map as "moving" three days after its last fix, which is the one lie a
dispatcher cannot catch by looking.

This job closes that gap: a truck whose newest fix is older than the silence
window is set to ``offline``. The next ping puts it straight back, because the
writer derives status from speed without looking at the previous value.

``maintenance`` is left alone — a truck in the workshop is silent on purpose,
and that status is set by a person, not by a ping.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import TruckStatus
from app.models.trucks import Truck, TruckLocation

# Statuses a ping produces. Only these can go stale; ``offline`` already says
# "no signal" and ``maintenance`` is a human decision.
_PING_STATUSES = (TruckStatus.moving, TruckStatus.idle, TruckStatus.stopped)


async def mark_silent_trucks_offline(
    db: AsyncSession,
    silent_after: timedelta,
    *,
    now: datetime | None = None,
) -> int:
    """Set ``offline`` on every truck silent for longer than ``silent_after``.

    Returns how many trucks changed. Idempotent: a truck already offline is
    not matched again.
    """
    cutoff = (now or datetime.now(timezone.utc)) - silent_after
    silent = select(TruckLocation.truck_id).where(TruckLocation.recorded_at < cutoff)

    result = await db.execute(
        update(Truck)
        .where(Truck.id.in_(silent), Truck.status.in_(_PING_STATUSES))
        .values(status=TruckStatus.offline, updated_at=datetime.now(timezone.utc))
        .execution_options(synchronize_session=False)
    )
    await db.commit()
    return result.rowcount or 0
