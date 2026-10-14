"""Drivers' stays in Russia: the desk's record and corrections, and the
driver's own count. See :mod:`app.services.russia_stay` for the 90-in-180 rule.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.deps.auth import get_current_driver, get_org_id, require_role
from app.models.drivers import Driver
from app.models.enums import UserRole
from app.models.russia_stays import DriverRussiaStay
from app.services.russia_stay import StaySummary, summarize
from app.services.russia_stay_records import (
    local_today,
    stays_for,
    summaries_for_org,
    summary_for,
    to_stays,
)

router = APIRouter(tags=["Russia stays"])

_DESK = require_role(UserRole.admin, UserRole.manager, UserRole.operator)


class StaySummaryOut(BaseModel):
    in_russia: bool
    entered_on: Optional[date] = None
    day_of_stay: Optional[int] = None
    days_used: int
    days_available: int
    must_leave_by: Optional[date] = None
    days_to_leave: Optional[int] = None
    overstay_days: int


class StayOut(BaseModel):
    id: uuid.UUID
    entered_on: date
    left_on: Optional[date] = None
    source: str
    trip_id: Optional[uuid.UUID] = None
    note: Optional[str] = None


class DriverStaysOut(BaseModel):
    summary: StaySummaryOut
    stays: list[StayOut]


class FleetStayOut(BaseModel):
    driver_id: uuid.UUID
    driver_name: str
    summary: StaySummaryOut


class StayIn(BaseModel):
    entered_on: date
    left_on: Optional[date] = None
    note: Optional[str] = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def _dates_make_sense(self) -> "StayIn":
        _check_dates(self.entered_on, self.left_on)
        return self


class StayPatch(BaseModel):
    entered_on: Optional[date] = None
    left_on: Optional[date] = None
    note: Optional[str] = Field(default=None, max_length=200)


def _check_dates(entered_on: date, left_on: date | None) -> None:
    today = local_today(datetime.now(timezone.utc))
    if entered_on > today:
        raise ValueError("Дата въезда не может быть в будущем")
    if left_on is not None and left_on < entered_on:
        raise ValueError("Дата выезда раньше даты въезда")
    if left_on is not None and left_on > today:
        raise ValueError("Дата выезда не может быть в будущем")


def _summary_out(summary: StaySummary) -> StaySummaryOut:
    return StaySummaryOut(**summary.__dict__)


def _stay_out(row: DriverRussiaStay) -> StayOut:
    return StayOut(
        id=row.id,
        entered_on=row.entered_on,
        left_on=row.left_on,
        source=row.source,
        trip_id=row.trip_id,
        note=row.note,
    )


async def _owned_driver(db: AsyncSession, driver_id: uuid.UUID, org_id: uuid.UUID) -> Driver:
    driver = (
        await db.execute(select(Driver).where(Driver.id == driver_id, Driver.org_id == org_id))
    ).scalar_one_or_none()
    if driver is None:
        raise HTTPException(status_code=404, detail="Водитель не найден")
    return driver


def _check_overlap(rows: list[DriverRussiaStay], entered_on: date, left_on: date | None, skip: uuid.UUID | None) -> None:
    """A driver is in one place at a time: no two stays share a day, and only one is open."""
    today = local_today(datetime.now(timezone.utc))
    end = left_on or today
    for row in rows:
        if row.id == skip:
            continue
        if left_on is None and row.left_on is None:
            raise HTTPException(status_code=409, detail="У водителя уже есть незакрытый въезд в РФ")
        row_end = row.left_on or today
        # Sharing a boundary day is allowed — out and back in on the same day
        # is real, and the count takes the union of days.
        if entered_on < row_end and row.entered_on < end:
            raise HTTPException(status_code=409, detail="Даты пересекаются с другим пребыванием в РФ")


async def _driver_stays_out(db: AsyncSession, driver_id: uuid.UUID) -> DriverStaysOut:
    rows = await stays_for(db, driver_id)
    today = local_today(datetime.now(timezone.utc))
    return DriverStaysOut(
        summary=_summary_out(summarize(to_stays(rows), today=today)),
        stays=[_stay_out(r) for r in rows],
    )


@router.get("/api/russia-stays", response_model=list[FleetStayOut])
async def fleet_stays(
    db: AsyncSession = Depends(get_db),
    org: uuid.UUID = Depends(get_org_id),
    _user=Depends(_DESK),
):
    """Every driver whose Russia days still count, the closest to the limit first."""
    summaries = await summaries_for_org(db, org, local_today(datetime.now(timezone.utc)))
    if not summaries:
        return []
    names = dict(
        (await db.execute(select(Driver.id, Driver.name).where(Driver.id.in_(summaries)))).all()
    )
    rows = [
        FleetStayOut(driver_id=driver_id, driver_name=names.get(driver_id, "—"), summary=_summary_out(s))
        for driver_id, s in summaries.items()
    ]
    # Inside Russia and nearest the deadline first; then the rest by days used.
    return sorted(
        rows,
        key=lambda r: (
            not r.summary.in_russia,
            r.summary.days_to_leave if r.summary.days_to_leave is not None else 10_000,
            -r.summary.days_used,
        ),
    )


@router.get("/api/drivers/{driver_id}/russia-stays", response_model=DriverStaysOut)
async def driver_stays(
    driver_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    org: uuid.UUID = Depends(get_org_id),
    _user=Depends(_DESK),
):
    await _owned_driver(db, driver_id, org)
    return await _driver_stays_out(db, driver_id)


@router.post(
    "/api/drivers/{driver_id}/russia-stays",
    response_model=StayOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_stay(
    driver_id: uuid.UUID,
    data: StayIn,
    db: AsyncSession = Depends(get_db),
    org: uuid.UUID = Depends(get_org_id),
    _user=Depends(_DESK),
):
    """A stay the app missed — typed from the migration card."""
    await _owned_driver(db, driver_id, org)
    _check_overlap(await stays_for(db, driver_id), data.entered_on, data.left_on, skip=None)
    row = DriverRussiaStay(
        org_id=org,
        driver_id=driver_id,
        entered_on=data.entered_on,
        left_on=data.left_on,
        note=data.note,
        source="manual",
    )
    db.add(row)
    await db.commit()
    return _stay_out(row)


@router.patch("/api/drivers/{driver_id}/russia-stays/{stay_id}", response_model=StayOut)
async def update_stay(
    driver_id: uuid.UUID,
    stay_id: uuid.UUID,
    data: StayPatch,
    db: AsyncSession = Depends(get_db),
    org: uuid.UUID = Depends(get_org_id),
    _user=Depends(_DESK),
):
    await _owned_driver(db, driver_id, org)
    rows = await stays_for(db, driver_id)
    row = next((r for r in rows if r.id == stay_id), None)
    if row is None:
        raise HTTPException(status_code=404, detail="Запись не найдена")
    changes = data.model_dump(exclude_unset=True)
    entered_on = changes.get("entered_on", row.entered_on) or row.entered_on
    left_on = changes.get("left_on", row.left_on)
    try:
        _check_dates(entered_on, left_on)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _check_overlap(rows, entered_on, left_on, skip=row.id)
    row.entered_on, row.left_on = entered_on, left_on
    if "note" in changes:
        row.note = changes["note"]
    row.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return _stay_out(row)


@router.delete(
    "/api/drivers/{driver_id}/russia-stays/{stay_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_stay(
    driver_id: uuid.UUID,
    stay_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    org: uuid.UUID = Depends(get_org_id),
    _user=Depends(_DESK),
):
    await _owned_driver(db, driver_id, org)
    row = (
        await db.execute(
            select(DriverRussiaStay).where(
                DriverRussiaStay.id == stay_id, DriverRussiaStay.driver_id == driver_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Запись не найдена")
    await db.delete(row)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/api/me/russia-stay", response_model=StaySummaryOut)
async def my_russia_stay(
    driver: Driver = Depends(get_current_driver),
    db: AsyncSession = Depends(get_db),
):
    """The driver's own count, for the card on the app's home screen."""
    return _summary_out(await summary_for(db, driver.id, local_today(datetime.now(timezone.utc))))
