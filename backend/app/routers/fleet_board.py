"""The fleet board — every truck, where it is, its export and import — and the
dispatchers' group it is posted to each morning.

See :mod:`app.services.fleet_board` for what goes in a row and
:mod:`app.services.fleet_board_digest` for the group and the morning copy.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.deps.auth import get_org_id, require_role
from app.models.dispatch_groups import DispatchTelegramGroup
from app.models.enums import TripStatus, UserRole
from app.services import fleet_board_digest, fleet_board_xlsx
from app.services.fleet_board import BoardRow, BoardTrip, build_board

router = APIRouter(tags=["Fleet board"])

_DESK = require_role(UserRole.admin, UserRole.manager, UserRole.operator)


class BoardTripOut(BaseModel):
    trip_id: uuid.UUID
    reference: str
    route: str
    loading_date: Optional[date] = None
    unloading_date: Optional[date] = None
    is_loaded: bool
    status: TripStatus


class BoardRowOut(BaseModel):
    position: int
    truck_id: uuid.UUID
    plate: str
    location: Optional[str] = None
    location_at: Optional[datetime] = None
    export_trip: Optional[BoardTripOut] = None
    import_trip: Optional[BoardTripOut] = None


class BoardOut(BaseModel):
    day: date
    rows: list[BoardRowOut]


class DispatchGroupOut(BaseModel):
    # none: never linked. pending: link made, bot not yet added.
    # linked: posting to a group. lost: the bot was removed from the group.
    status: Literal["none", "pending", "linked", "lost"]
    chat_title: Optional[str] = None
    activated_at: Optional[datetime] = None
    board_sent_on: Optional[date] = None
    # Only while pending: once the bot is in a group the link is spent.
    deep_link: Optional[str] = None


def _trip_out(trip: BoardTrip | None) -> BoardTripOut | None:
    return BoardTripOut(**trip.__dict__) if trip else None


def _row_out(row: BoardRow) -> BoardRowOut:
    return BoardRowOut(
        position=row.position,
        truck_id=row.truck_id,
        plate=row.plate,
        location=row.location,
        location_at=row.location_at,
        export_trip=_trip_out(row.export_trip),
        import_trip=_trip_out(row.import_trip),
    )


def _group_out(row: DispatchTelegramGroup | None) -> DispatchGroupOut:
    if row is None:
        return DispatchGroupOut(status="none")
    common = dict(chat_title=row.chat_title, activated_at=row.activated_at, board_sent_on=row.board_sent_on)
    if row.chat_id:
        return DispatchGroupOut(status="linked", **common)
    if row.activated_at:
        return DispatchGroupOut(status="lost", **common)
    return DispatchGroupOut(status="pending", deep_link=fleet_board_digest.build_deep_link(row.token))


@router.get("/api/fleet-board", response_model=BoardOut)
async def get_board(
    db: AsyncSession = Depends(get_db),
    org: uuid.UUID = Depends(get_org_id),
    _user=Depends(_DESK),
):
    rows = await build_board(db, org)
    return BoardOut(day=fleet_board_digest.local_day(datetime.now(timezone.utc)), rows=[_row_out(r) for r in rows])


@router.get("/api/fleet-board.xlsx")
async def get_board_xlsx(
    db: AsyncSession = Depends(get_db),
    org: uuid.UUID = Depends(get_org_id),
    _user=Depends(_DESK),
):
    day = fleet_board_digest.local_day(datetime.now(timezone.utc))
    content = fleet_board_xlsx.build_workbook(await build_board(db, org), day)
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fleet_board_xlsx.filename_for(day)}"'},
    )


@router.get("/api/fleet-board/telegram-group", response_model=DispatchGroupOut)
async def get_dispatch_group(
    db: AsyncSession = Depends(get_db),
    org: uuid.UUID = Depends(get_org_id),
    _user=Depends(_DESK),
):
    return _group_out(await fleet_board_digest.group_for(db, org))


@router.post("/api/fleet-board/telegram-group", response_model=DispatchGroupOut)
async def link_dispatch_group(
    db: AsyncSession = Depends(get_db),
    org: uuid.UUID = Depends(get_org_id),
    _user=Depends(_DESK),
):
    return _group_out(await fleet_board_digest.mint_link(db, org))


@router.delete("/api/fleet-board/telegram-group", response_model=DispatchGroupOut)
async def unlink_dispatch_group(
    db: AsyncSession = Depends(get_db),
    org: uuid.UUID = Depends(get_org_id),
    _user=Depends(_DESK),
):
    await db.execute(delete(DispatchTelegramGroup).where(DispatchTelegramGroup.org_id == org))
    await db.commit()
    return _group_out(None)


@router.post("/api/fleet-board/telegram-group/send", response_model=DispatchGroupOut)
async def send_board_now(
    db: AsyncSession = Depends(get_db),
    org: uuid.UUID = Depends(get_org_id),
    _user=Depends(_DESK),
):
    """Post today's board now — after a morning of corrections, or to try the link."""
    row = await fleet_board_digest.group_for(db, org)
    if row is None or not row.chat_id:
        raise HTTPException(status_code=409, detail="Группа диспетчеров не подключена")
    now = datetime.now(timezone.utc)
    # Inside the morning window a manual send is that morning's board; before
    # it, a test that must not cancel the 08:00 copy.
    sent = await fleet_board_digest.send_board(db, row, now=now, mark_sent=fleet_board_digest.in_window(now))
    if not sent:
        raise HTTPException(status_code=502, detail="Telegram не принял файл, попробуйте ещё раз")
    return _group_out(row)
