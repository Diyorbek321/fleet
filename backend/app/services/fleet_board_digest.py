"""The dispatchers' group: binding it, and the fleet board it gets each morning.

**Binding** works like a truck's group (:mod:`app.services.trip_orders`): the
panel hands out a ``startgroup`` link carrying a one-time ``dispatch_`` token,
and whichever group the bot is added to with it is bound. The chat id never
passes through the panel.

**The morning copy.** The scheduler ticks every fifteen minutes; the clock is
checked here, as :mod:`app.services.owner_alerts.briefing` does, so "when does
it fire" is read in one place. From the target hour (Tashkent) until the window
closes, each linked group that has not had today's board gets it, and
``board_sent_on`` records the day — that, not the hour, is what makes it once.
The window is there so a restart across 08:00 costs a late board, not a day's.
"""
from __future__ import annotations

import os
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import logger
from app.models.dispatch_groups import DispatchTelegramGroup
from app.models.organizations import Organization
from app.services import fleet_board_xlsx
from app.services.fleet_board import build_board
from app.services.owner_alerts.bus import _send_document as send_document
from app.services.period_reports import report_tz
from app.services.trip_orders import mint_group_token, parse_start_payload

TOKEN_PREFIX = "dispatch_"
DEFAULT_BOARD_HOUR = 8
# Hours after the target the board may still go out (a late start, a restart).
CATCHUP_HOURS = 4


def local_day(now: datetime) -> date:
    return now.astimezone(report_tz()).date()


def board_hour() -> int:
    """Local hour the board targets: ``FLEET_BOARD_HOUR_LOCAL``, else 08:00."""
    try:
        hour = int(os.environ.get("FLEET_BOARD_HOUR_LOCAL", DEFAULT_BOARD_HOUR))
    except ValueError:
        return DEFAULT_BOARD_HOUR
    return hour if 0 <= hour <= 23 else DEFAULT_BOARD_HOUR


def in_window(now: datetime) -> bool:
    hour = now.astimezone(report_tz()).hour
    return board_hour() <= hour < board_hour() + CATCHUP_HOURS


# ── Linking ──────────────────────────────────────────────────────────────


def build_deep_link(token: str) -> str:
    username = settings.telegram_bot_username.strip().lstrip("@")
    if username:
        return f"https://t.me/{username}?startgroup={TOKEN_PREFIX}{token}"
    return f"tg://resolve?startgroup={TOKEN_PREFIX}{token}"


def parse_start(text: str) -> str | None:
    """The token from ``/start dispatch_<token>`` or ``/start@bot dispatch_<token>``."""
    return parse_start_payload(text, TOKEN_PREFIX)


async def group_for(db: AsyncSession, org_id: uuid.UUID) -> DispatchTelegramGroup | None:
    return (
        await db.execute(select(DispatchTelegramGroup).where(DispatchTelegramGroup.org_id == org_id))
    ).scalar_one_or_none()


async def mint_link(db: AsyncSession, org_id: uuid.UUID) -> DispatchTelegramGroup:
    """A fresh link. Any group already linked is let go: one group per company."""
    row = await group_for(db, org_id)
    if row is None:
        row = DispatchTelegramGroup(org_id=org_id, token=mint_group_token())
        db.add(row)
    else:
        row.token = mint_group_token()
        row.chat_id = None
        row.chat_title = None
        row.activated_at = None
    await db.commit()
    return row


async def activate(db: AsyncSession, token: str, chat: dict) -> str | None:
    """Bind the group the bot was just added to. Returns the reply, or None.

    None for an unknown token: anyone can type ``/start dispatch_x`` in a group.
    """
    if chat.get("type") not in ("group", "supergroup"):
        return "Эта ссылка добавляет бота в группу диспетчеров — откройте её и выберите группу."
    row = (
        await db.execute(select(DispatchTelegramGroup).where(DispatchTelegramGroup.token == token))
    ).scalar_one_or_none()
    if row is None:
        return None
    # The token is spent once used: a second group opening the same link must
    # not take over — not even after the bot has left the first one, when the
    # panel shows "lost" and only a fresh link may bind a group again.
    if row.activated_at is not None and row.chat_id != str(chat["id"]):
        return None
    row.chat_id = str(chat["id"])
    row.chat_title = (chat.get("title") or "")[:200] or None
    row.activated_at = datetime.now(timezone.utc)
    await db.commit()
    return (
        "✅ Группа диспетчеров подключена. Каждое утро сюда будет приходить "
        "таблица автопарка: где машины, экспорт и импорт."
    )


async def follow_membership(db: AsyncSession, update: dict) -> None:
    """The bot removed from the group, or the group upgraded to a supergroup."""
    member = update.get("my_chat_member")
    if isinstance(member, dict):
        chat_id = str((member.get("chat") or {}).get("id", ""))
        status = ((member.get("new_chat_member") or {}).get("status")) or ""
        if chat_id and status in ("left", "kicked"):
            await _retarget(db, chat_id, None)
        return
    message = update.get("message")
    if isinstance(message, dict) and message.get("migrate_to_chat_id"):
        old_id = str((message.get("chat") or {}).get("id", ""))
        await _retarget(db, old_id, str(message["migrate_to_chat_id"]))


async def _retarget(db: AsyncSession, chat_id: str, new_chat_id: str | None) -> None:
    rows = (
        await db.execute(select(DispatchTelegramGroup).where(DispatchTelegramGroup.chat_id == chat_id))
    ).scalars().all()
    for row in rows:
        row.chat_id = new_chat_id
    if rows:
        await db.commit()


# ── Sending ──────────────────────────────────────────────────────────────


async def send_board(
    db: AsyncSession, row: DispatchTelegramGroup, *, now: datetime, mark_sent: bool = False
) -> bool:
    """Build today's board for the group's company and post it. Returns whether it went.

    Only the scheduler passes ``mark_sent``: a dispatcher's "send now" at 07:00
    is a test or a correction, and must not stand in for the 08:00 board.
    """
    if not row.chat_id:
        return False
    day = local_day(now)
    board = await build_board(db, row.org_id)
    caption = (
        f"📋 <b>Автопарк на {day:%d.%m.%Y}</b>\n"
        f"Машин: {len(board)} · "
        f"экспорт: {sum(1 for r in board if r.export_trip)} · "
        f"импорт: {sum(1 for r in board if r.import_trip)}"
    )
    result = await send_document(
        row.chat_id,
        fleet_board_xlsx.filename_for(day),
        fleet_board_xlsx.build_workbook(board, day),
        caption,
    )
    if not result.ok:
        # 403 only: the bot was removed or blocked. A 400 can as well be a file
        # Telegram did not like, and unlinking on it would drop every morning
        # after until someone noticed.
        if result.status_code == 403:
            # Show it in the panel so the desk relinks.
            logger.warning("dispatch_group_unreachable", org_id=str(row.org_id))
            row.chat_id = None
            await db.commit()
        return False
    if mark_sent:
        row.board_sent_on = day
        await db.commit()
    return True


async def run(db: AsyncSession, *, now: datetime | None = None) -> int:
    """Scheduler entry point. Returns how many groups got the board."""
    now = now or datetime.now(timezone.utc)
    if not in_window(now):
        return 0
    day = local_day(now)
    due = (
        await db.execute(
            select(DispatchTelegramGroup.id, DispatchTelegramGroup.org_id)
            .join(Organization, Organization.id == DispatchTelegramGroup.org_id)
            .where(
                Organization.is_active.is_(True),
                DispatchTelegramGroup.chat_id.is_not(None),
                (DispatchTelegramGroup.board_sent_on.is_(None))
                | (DispatchTelegramGroup.board_sent_on < day),
            )
        )
    ).all()

    sent = 0
    # Plain ids, each row loaded in its turn: a rollback after one company's
    # failure expires every instance in the session, and the next company's
    # row must not be one of them.
    for group_id, org_id in due:
        try:
            row = await db.get(DispatchTelegramGroup, group_id)
            if row is not None:
                sent += await send_board(db, row, now=now, mark_sent=True)
        except Exception:  # noqa: BLE001 — one company's bad data must not cost the rest theirs.
            logger.exception("fleet_board_send_failed", org_id=str(org_id))
            await db.rollback()
    if sent:
        logger.info("fleet_board_sent", groups=sent, day=day.isoformat())
    return sent
