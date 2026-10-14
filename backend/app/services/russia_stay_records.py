"""Reading and writing a driver's Russia stays. The count itself is in
:mod:`app.services.russia_stay`; this is where the rows come from.

**Written by the border checkpoint.** A driver marking "crossed the border" at
the KZ–RU crossing is entering Russia on an export (``uz_ru``) and leaving it
on an import (``ru_uz``). The trip's direction is what tells the two apart —
the crossing is the same place both ways. A trip with no direction, or a
crossing anywhere else, writes nothing.

Entry opens a stay unless one is already open (marking the crossing twice, or
a second export trip while still inside, must not start the clock again).
Exit closes the open stay; with none open there is nothing to close, and the
desk fills the gap by hand.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger
from app.models.enums import StagePlace, TripStage
from app.models.russia_stays import DriverRussiaStay
from app.models.trips import Trip
from app.services.period_reports import report_tz
from app.services.russia_stay import WINDOW_DAYS, Stay, StaySummary, summarize

_RU_CROSSING = StagePlace.kz_ru
_INTO_RUSSIA = "uz_ru"
_OUT_OF_RUSSIA = "ru_uz"
_UNKNOWN_EXIT_NOTE = "Выезд не отмечен — укажите точную дату"


def local_today(now: datetime) -> date:
    return now.astimezone(report_tz()).date()


async def stays_for(db: AsyncSession, driver_id: uuid.UUID) -> list[DriverRussiaStay]:
    return list(
        (
            await db.execute(
                select(DriverRussiaStay)
                .where(DriverRussiaStay.driver_id == driver_id)
                .order_by(DriverRussiaStay.entered_on.desc())
            )
        ).scalars()
    )


def to_stays(rows: list[DriverRussiaStay]) -> list[Stay]:
    return [Stay(r.entered_on, r.left_on) for r in rows]


async def summary_for(db: AsyncSession, driver_id: uuid.UUID, today: date) -> StaySummary:
    return summarize(to_stays(await stays_for(db, driver_id)), today=today)


async def summaries_for_org(
    db: AsyncSession, org_id: uuid.UUID, today: date
) -> dict[uuid.UUID, StaySummary]:
    """Every driver with a stay that still counts: open, or inside the window."""
    horizon = today - timedelta(days=WINDOW_DAYS)
    rows = (
        await db.execute(
            select(DriverRussiaStay).where(
                DriverRussiaStay.org_id == org_id,
                (DriverRussiaStay.left_on.is_(None)) | (DriverRussiaStay.left_on >= horizon),
            )
        )
    ).scalars().all()
    by_driver: dict[uuid.UUID, list[Stay]] = {}
    for row in rows:
        by_driver.setdefault(row.driver_id, []).append(Stay(row.entered_on, row.left_on))
    return {driver_id: summarize(stays, today=today) for driver_id, stays in by_driver.items()}


async def _open_stay(db: AsyncSession, driver_id: uuid.UUID) -> DriverRussiaStay | None:
    return (
        await db.execute(
            select(DriverRussiaStay).where(
                DriverRussiaStay.driver_id == driver_id, DriverRussiaStay.left_on.is_(None)
            )
        )
    ).scalar_one_or_none()


async def record_crossing(
    db: AsyncSession,
    trip: Trip,
    stage: TripStage | None,
    place: StagePlace | None,
    now: datetime,
) -> None:
    """Open or close the driver's stay for a KZ–RU crossing. The caller commits.

    Never raises: this is a side effect of the driver's checkpoint, and losing
    the checkpoint because the stay could not be written would be the worse
    failure. Written in a savepoint, so a double tap racing itself into the
    one-open-stay index rolls back only the stay, not the checkpoint.
    """
    if stage is not TripStage.crossed_border or place is not _RU_CROSSING or trip.driver_id is None:
        return
    try:
        async with db.begin_nested():
            await _apply_crossing(db, trip, local_today(now), now)
    except IntegrityError:
        logger.info("russia_stay_entry_raced", driver_id=str(trip.driver_id))
    except Exception:  # noqa: BLE001 — see the docstring
        logger.exception("russia_stay_record_failed", trip_id=str(trip.id))


async def _apply_crossing(db: AsyncSession, trip: Trip, today: date, now: datetime) -> None:
    open_stay = await _open_stay(db, trip.driver_id)
    if trip.direction == _INTO_RUSSIA:
        if open_stay is not None:
            if open_stay.trip_id == trip.id or open_stay.entered_on >= today:
                return  # the same crossing marked twice
            # Inside already, by the record — yet crossing in again on another
            # trip: the way out was never marked. Its date is unknown, so the
            # stay is closed as late as it can have been (yesterday). That errs
            # towards more days in Russia, never fewer, and the note asks the
            # desk to put in the real date.
            open_stay.left_on = today - timedelta(days=1)
            open_stay.note = _UNKNOWN_EXIT_NOTE
            open_stay.updated_at = now
            await db.flush()
        db.add(
            DriverRussiaStay(
                org_id=trip.org_id,
                driver_id=trip.driver_id,
                entered_on=today,
                source="auto",
                trip_id=trip.id,
            )
        )
        await db.flush()
    elif trip.direction == _OUT_OF_RUSSIA and open_stay is not None and open_stay.entered_on <= today:
        open_stay.left_on = today
        open_stay.updated_at = now
