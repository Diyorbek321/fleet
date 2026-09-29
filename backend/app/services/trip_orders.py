"""The order sheet ("заявка") posted to a truck's Telegram group on a new trip.

The layout is the one dispatchers already paste into those groups by hand, so
the driver reads the bot's post exactly as they read a person's:

    #26Импорт

    Погран. переход через МАЙСКИЙ !!!

    📍 Маршрут: Елабуга - Ташкент
    📦 Отправитель: …
    …
    ⚠️ ОБЯЗАТЕЛЬНО К ИСПОЛНЕНИЮ:
    1️⃣ …

    <dispatcher phones> ПОДТВЕРЖДАЕТЕ ЗАЯВКУ ?

A line whose field is empty is left out rather than printed blank. No money:
the group has the driver in it, and the rate is between the company and the
customer.

Sent once per trip (``trips.order_sent_at``), whether the truck was chosen at
creation or on a later edit, and never raises — the trip was saved, and a
Telegram outage must not turn that into an error.
"""
from __future__ import annotations

import html
import re
import secrets
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.logging import logger
from app.models.organizations import Organization
from app.models.trips import Trip
from app.models.truck_groups import TruckTelegramGroup
from app.services.period_reports import report_tz
from app.services.telegram import send_message

__all__ = [
    "DEFAULT_RULES",
    "GROUP_TOKEN_PREFIX",
    "build_group_deep_link",
    "format_trip_order",
    "mint_group_token",
    "parse_group_start",
    "send_trip_order",
    "send_trip_order_background",
]

GROUP_TOKEN_PREFIX = "truck_"

# The built-in "ОБЯЗАТЕЛЬНО К ИСПОЛНЕНИЮ" list, used until a company writes
# its own in the panel.
DEFAULT_RULES = (
    "1️⃣ Чистый, убранный кузов — без лишних вещей\n"
    "2️⃣ При подозрении на перегруз — обвес по осям до границы\n"
    "3️⃣ Фото груза при погрузке\n"
    "4️⃣ Скан всех документов (ТТН, CMR и т.д.)\n"
    "5️⃣ Каждое утро отправлять локацию 📍\n"
    "6️⃣ Без согласования ❗\n"
    " — не заезжать на растаможку\n"
    " — не производить выгрузку\n"
    "7️⃣ После выгрузки груза необходимо сразу же отправить СМР в хорошем качестве."
)

# "uz_ru" leaves Uzbekistan, "ru_uz" arrives. Named from the Uzbek side,
# because that is whose customs the dispatcher is dealing with.
_DIRECTION_TAG = {"uz_ru": "Экспорт", "ru_uz": "Импорт"}

_SEPARATOR = "———"


# ── Linking ──────────────────────────────────────────────────────────────


def mint_group_token() -> str:
    # 24 bytes → 32 URL-safe chars; with the prefix well inside Telegram's
    # 64-char limit for a start parameter.
    return secrets.token_urlsafe(24)


def build_group_deep_link(token: str) -> str:
    """``startgroup`` opens Telegram's "add to group" picker for the bot."""
    username = settings.telegram_bot_username.strip().lstrip("@")
    if username:
        return f"https://t.me/{username}?startgroup={GROUP_TOKEN_PREFIX}{token}"
    return f"tg://resolve?startgroup={GROUP_TOKEN_PREFIX}{token}"


def parse_group_start(text: str) -> str | None:
    """The token from ``/start truck_<token>`` or ``/start@bot truck_<token>``.

    In a group Telegram addresses the command to the bot by name, so the
    ``@bot`` suffix is the normal case here, not the exception.
    """
    if not text:
        return None
    parts = text.strip().split(maxsplit=1)
    if len(parts) != 2 or parts[0].split("@", 1)[0] != "/start":
        return None
    payload = parts[1].strip()
    if not payload.startswith(GROUP_TOKEN_PREFIX):
        return None
    token = payload[len(GROUP_TOKEN_PREFIX):]
    if not token or len(token) > 48 or not all(c.isalnum() or c in "-_" for c in token):
        return None
    return token


# ── Text ─────────────────────────────────────────────────────────────────


def _esc(value: str) -> str:
    return html.escape(value.strip(), quote=False)


def _order_number(reference: str) -> str:
    """The trailing number of the reference, without padding: "Angren Tek-0026" → "26"."""
    match = re.search(r"(\d+)\s*$", reference or "")
    return str(int(match.group(1))) if match else (reference or "").strip()


def _tonnes(weight_kg) -> str | None:
    if not weight_kg:
        return None
    tonnes = float(weight_kg) / 1000
    text = f"{tonnes:.1f}".rstrip("0").rstrip(".")
    return f"{text} тн"


def _field(emoji: str, label: str, value: str | None) -> str | None:
    if not value or not value.strip():
        return None
    return f"{emoji} {label}: {_esc(value)}"


def format_trip_order(trip: Trip, org: Organization | None) -> str:
    """The whole post, as Telegram HTML. Pure, so it is testable alone."""
    tag = f"#{_order_number(trip.reference)}{_DIRECTION_TAG.get(trip.direction or '', '')}"
    blocks: list[list[str | None]] = [[_esc(tag)]]

    if trip.border_crossing and trip.border_crossing.strip():
        blocks.append([f"Погран. переход через {_esc(trip.border_crossing.upper())} !!!"])

    route = " - ".join(p.strip() for p in (trip.origin_name, trip.destination_name) if p and p.strip())
    cargo = " ".join(p for p in ((trip.cargo_description or "").strip(), _tonnes(trip.cargo_weight_kg)) if p)
    loading_date = (
        trip.scheduled_start.astimezone(report_tz()).strftime("%d.%m")
        if trip.scheduled_start
        else None
    )
    blocks.append([
        _field("📍", "Маршрут", route),
        _field("📦", "Отправитель", trip.shipper),
        _field("🏭", "Адрес погрузки", trip.loading_address),
        _field("📦", "Груз", cargo),
        _field("📅", "Дата погрузки", loading_date),
        _field("📞", "Контакты", trip.loading_contact),
    ])
    blocks.append([_SEPARATOR])
    blocks.append([
        _field("📦", "Получатель", trip.consignee),
        _field("🛃", "Растаможка", trip.customs_point),
        _field("📍", "Адрес выгрузки", trip.unloading_address),
        _field("📞", "Контакты", trip.declarant_contact),
    ])

    rules = (org.trip_order_rules if org and org.trip_order_rules else DEFAULT_RULES).strip()
    blocks.append(["⚠️ <b>ОБЯЗАТЕЛЬНО К ИСПОЛНЕНИЮ:</b>", _esc(rules)])

    footer = (org.trip_order_footer or "").strip() if org else ""
    confirm = "<b>ПОДТВЕРЖДАЕТЕ ЗАЯВКУ ?</b>"
    blocks.append([f"{_esc(footer)} {confirm}" if footer else confirm])

    # Each field is its own paragraph, as in the hand-written sheet.
    paragraphs = ["\n\n".join(line for line in block if line) for block in blocks]
    return "\n\n".join(p for p in paragraphs if p)


# ── Sending ──────────────────────────────────────────────────────────────


async def linked_group(db: AsyncSession, truck_id: uuid.UUID) -> TruckTelegramGroup | None:
    group = (
        await db.execute(select(TruckTelegramGroup).where(TruckTelegramGroup.truck_id == truck_id))
    ).scalar_one_or_none()
    return group if group is not None and group.chat_id else None


async def send_trip_order(db: AsyncSession, trip: Trip, *, force: bool = False) -> bool:
    """Post the order to the truck's group. Returns whether it went out.

    Without ``force`` a trip already announced is skipped, which is what keeps
    the automatic post at once per trip. ``force`` is the dispatcher's
    "send again" button.
    """
    if trip.truck_id is None or (trip.order_sent_at and not force):
        return False
    group = await linked_group(db, trip.truck_id)
    if group is None:
        return False
    org = await db.get(Organization, trip.org_id)

    result = await send_message(group.chat_id, format_trip_order(trip, org))
    if not result.ok:
        if result.permanently_failed:
            # Bot removed or group deleted: stop pretending it is linked, so
            # the panel shows it and the dispatcher relinks.
            logger.warning("truck_group_unreachable", truck_id=str(trip.truck_id))
            group.chat_id = None
            await db.commit()
        return False

    trip.order_sent_at = datetime.now(timezone.utc)
    await db.commit()
    logger.info("trip_order_sent", trip_id=str(trip.id), truck_id=str(trip.truck_id))
    return True


async def send_trip_order_background(trip_id: uuid.UUID) -> None:
    """``BackgroundTasks`` entry point: runs after the response, on its own session."""
    try:
        async with SessionLocal() as db:
            trip = await db.get(Trip, trip_id)
            if trip is not None:
                await send_trip_order(db, trip)
    except Exception:  # noqa: BLE001 — nothing to propagate to
        logger.exception("trip_order_send_failed", trip_id=str(trip_id))


# ── Webhook side ─────────────────────────────────────────────────────────


async def activate_truck_group(db: AsyncSession, token: str, chat: dict) -> str | None:
    """Bind the group the bot was just added to. Returns the reply, or None.

    None when the token matches nothing: an unknown token in a group gets no
    answer at all, because anyone can type ``/start truck_x`` there.
    """
    if chat.get("type") not in ("group", "supergroup"):
        return "Эта ссылка добавляет бота в группу машины — откройте её и выберите группу."
    group = (
        await db.execute(select(TruckTelegramGroup).where(TruckTelegramGroup.token == token))
    ).scalar_one_or_none()
    if group is None:
        return None
    # The token is spent: a second group opening the same link must not take
    # the truck over.
    if group.chat_id and group.chat_id != str(chat["id"]):
        return None

    from app.models.trucks import Truck  # local: keeps the module import-light

    truck = await db.get(Truck, group.truck_id)
    group.chat_id = str(chat["id"])
    group.chat_title = (chat.get("title") or "")[:200] or None
    group.activated_at = datetime.now(timezone.utc)
    await db.commit()
    plate = truck.plate_number if truck else ""
    return f"✅ Группа подключена к машине <b>{_esc(plate)}</b>. Новые заявки будут приходить сюда."


async def handle_group_membership(db: AsyncSession, update: dict) -> bool:
    """React to the bot leaving a group, or a group becoming a supergroup.

    Returns whether the update was one of these. A group upgraded to a
    supergroup gets a new chat id, and every post to the old one fails from
    then on — so the link follows it.
    """
    member = update.get("my_chat_member")
    if isinstance(member, dict):
        chat_id = str((member.get("chat") or {}).get("id", ""))
        status = ((member.get("new_chat_member") or {}).get("status")) or ""
        if chat_id and status in ("left", "kicked"):
            rows = (
                await db.execute(select(TruckTelegramGroup).where(TruckTelegramGroup.chat_id == chat_id))
            ).scalars().all()
            for row in rows:
                row.chat_id = None
            await db.commit()
        return True

    message = update.get("message")
    if isinstance(message, dict) and message.get("migrate_to_chat_id"):
        old_id = str((message.get("chat") or {}).get("id", ""))
        new_id = str(message["migrate_to_chat_id"])
        rows = (
            await db.execute(select(TruckTelegramGroup).where(TruckTelegramGroup.chat_id == old_id))
        ).scalars().all()
        for row in rows:
            row.chat_id = new_id
        await db.commit()
        return True
    return False
