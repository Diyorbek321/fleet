"""Keep every truck's current position labelled with a place name.

The live map and the truck detail page have always had an ``address`` field —
``truck_locations.address`` exists, the API returns it, the UI renders it — and
it has always been empty, because the only thing that could ever fill it was a
GPS device volunteering a street name in its payload. GT06 trackers do not.

So this job fills it: every tick, each truck's current fix is turned into
"Казахстан, Сарыагаш" and written back. Reads are almost always cache hits
(:mod:`app.services.geocoding` snaps coordinates to a ~1 km grid), so a fleet
that has not moved costs no provider calls at all — only the trucks that
crossed into a new cell do.

``MAX_LOOKUPS_PER_RUN`` bounds a tick: with the provider's one-request-per-
second policy, an uncapped run over a large platform would stretch a 15-minute
tick past the next one. Trucks that miss the cut are simply labelled on the
following tick — a slightly stale place name is a much smaller problem than a
scheduler that never finishes.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import logger
from app.models.trucks import TruckLocation
from app.services import geocoding

# Worst case one second each (the provider's rate limit), so a full run is
# bounded at about a minute.
MAX_LOOKUPS_PER_RUN = 60


async def refresh_location_addresses(db: AsyncSession) -> int:
    """Label each truck's current position. Returns how many rows changed.

    Unlabelled trucks come first: a blank address is a visibly broken cell in
    the UI, while an outdated one still tells the dispatcher roughly where the
    lorry is.
    """
    if not settings.geocoding_enabled:
        return 0

    rows = (
        await db.execute(
            select(TruckLocation)
            .order_by(
                TruckLocation.address.is_(None).desc(),
                TruckLocation.recorded_at.desc(),
            )
            .limit(MAX_LOOKUPS_PER_RUN)
        )
    ).scalars().all()

    updated = 0
    for row in rows:
        place = await geocoding.describe(float(row.latitude), float(row.longitude))
        if place is None or place == row.address:
            # Unknown place leaves the previous label alone: replacing "Toshkent"
            # with nothing because the geocoder blinked would be a regression on
            # the screen, not a correction.
            continue
        row.address = place
        updated += 1

    if updated:
        try:
            await db.commit()
        except Exception:  # noqa: BLE001 — a cosmetic label is never worth a crash
            await db.rollback()
            logger.exception("location_label_commit_failed")
            return 0

    logger.info("location_labels_refreshed", examined=len(rows), updated=updated)
    return updated
