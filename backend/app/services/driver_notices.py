"""Automatic notices on the driver's phone, so the dispatcher does not have to call.

Two sources:

**Events**, sent from the request that caused them (in the background, after
the response): a trip given to a driver, and a trip whose details the driver
works from — addresses, dates, customs, contacts — edited under them.

**Reminders**, found by the scheduler tick:

* loading tomorrow (from 18:00 the day before) and loading today (from 07:00);
* the CMR not uploaded two hours after delivery — the order sheet's rule 7;
* the truck's service due within a week or 500 km, and again when overdue;
* the driver's licence or the truck's insurance running out in 30 / 7 days,
  and on the day it has.

Every reminder carries a dedupe key naming the fact, so a reminder is sent
once however many ticks see it (``driver_messages.uq_driver_messages_org_key``).
A changed fact — a new loading date, the next service interval — gets a new
key and a new message. Russian, like every server-written text.

Never raises: a scheduler tick and a saved trip must both survive a failed push.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SessionLocal
from app.core.logging import logger
from app.models.driver_messages import DriverMessageKind
from app.models.drivers import Driver, DriverAssignment
from app.models.enums import DriverStatus, ServiceStatus, ServiceType, TripStatus
from app.models.maintenance import ServiceInterval
from app.models.trips import Trip, TripDocument
from app.models.trucks import Truck
from app.services.driver_messages import send_driver_message
from app.services.maintenance import DUE_SOON_DAYS, DUE_SOON_KM
from app.services.period_reports import report_tz
from app.services.trip_orders import order_number

__all__ = [
    "DRIVER_TRIP_FIELDS",
    "describe_trip_changes",
    "notify_trip_assigned_background",
    "notify_trip_changed_background",
    "run",
    "snapshot_trip",
]

# Loading reminders go out once the local clock passes these hours.
EVENING_BEFORE_HOUR = 18
MORNING_OF_HOUR = 7

# CMR: how long after delivery before asking, and how long to keep asking.
CMR_GRACE = timedelta(hours=2)
CMR_WINDOW = timedelta(days=3)

EXPIRY_BUCKETS = (30, 7)  # days left; plus the day it lapses

# A trip in one of these has not left yet — the only time a loading reminder helps.
_NOT_STARTED = (TripStatus.draft, TripStatus.planned)
_SETTLED = (TripStatus.delivered, TripStatus.cancelled)

_SERVICE_RU = {
    ServiceType.oil_change: "Замена масла",
    ServiceType.tire_rotation: "Перестановка шин",
    ServiceType.brake_inspection: "Проверка тормозов",
    ServiceType.engine_service: "Обслуживание двигателя",
    ServiceType.transmission: "Обслуживание трансмиссии",
    ServiceType.general: "Плановое ТО",
}

# The fields a driver acts on, and how the change notice names them. Money,
# the customer's commercial terms and internal notes are not the driver's.
DRIVER_TRIP_FIELDS: dict[str, str] = {
    "origin_name": "Откуда",
    "destination_name": "Куда",
    "border_crossing": "Погран. переход",
    "shipper": "Отправитель",
    "loading_address": "Адрес погрузки",
    "loading_contact": "Контакты погрузки",
    "scheduled_start": "Дата погрузки",
    "cargo_description": "Груз",
    "cargo_weight_kg": "Вес груза",
    "consignee": "Получатель",
    "customs_point": "Растаможка",
    "unloading_address": "Адрес выгрузки",
    "declarant_contact": "Контакты выгрузки",
    "scheduled_end": "Плановая доставка",
}

_MAX_VALUE_CHARS = 150


# ── Text helpers ─────────────────────────────────────────────────────────


def _local_date(moment: datetime) -> date:
    return moment.astimezone(report_tz()).date()


def _day_month(moment: datetime) -> str:
    return moment.astimezone(report_tz()).strftime("%d.%m")


def _route(trip) -> str:
    parts = [p.strip() for p in (trip.origin_name, trip.destination_name) if p and p.strip()]
    return " → ".join(parts)


def _trip_label(trip) -> str:
    route = _route(trip)
    return f"Рейс №{order_number(trip.reference)}" + (f" ({route})" if route else "")


def _format_value(field: str, value: Any) -> str:
    if value is None or (isinstance(value, str) and not value.strip()):
        return "удалено"
    if isinstance(value, datetime):
        return value.astimezone(report_tz()).strftime("%d.%m %H:%M")
    if field == "cargo_weight_kg":
        tonnes = float(value) / 1000
        return f"{tonnes:.1f}".rstrip("0").rstrip(".") + " тн"
    text = str(value).strip()
    return text if len(text) <= _MAX_VALUE_CHARS else text[: _MAX_VALUE_CHARS - 1] + "…"


def _comparable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, str):
        return value.strip() or None
    return value


# ── Events ───────────────────────────────────────────────────────────────


def snapshot_trip(trip: Trip) -> dict[str, Any]:
    """The driver-facing fields as they are now, to diff after an edit."""
    return {f: _comparable(getattr(trip, f, None)) for f in DRIVER_TRIP_FIELDS}


def describe_trip_changes(before: dict[str, Any], trip: Trip) -> list[tuple[str, str]]:
    """``(label, new value)`` for every driver-facing field the edit moved."""
    changes = []
    for field, label in DRIVER_TRIP_FIELDS.items():
        after = _comparable(getattr(trip, field, None))
        if after != before.get(field):
            changes.append((label, _format_value(field, getattr(trip, field, None))))
    return changes


async def _notify_assigned(db: AsyncSession, trip: Trip) -> None:
    if trip.driver_id is None or trip.status in _SETTLED:
        return
    lines = [f"Вам назначен {_trip_label(trip)}."]
    if trip.scheduled_start:
        lines.append(f"Погрузка: {_day_month(trip.scheduled_start)}.")
    if trip.loading_address:
        lines.append(f"Адрес погрузки: {_format_value('loading_address', trip.loading_address)}")
    lines.append("Подробности — в приложении, в разделе «Рейсы».")
    await send_driver_message(
        db,
        org_id=trip.org_id,
        driver_id=trip.driver_id,
        truck_id=trip.truck_id,
        kind=DriverMessageKind.trip_assigned,
        title="🚚 Новый рейс",
        body="\n".join(lines),
        # Once per trip and driver: a trip handed back to the same driver after
        # a swap is not news the second time.
        dedupe_key=f"trip_assigned:{trip.id}:{trip.driver_id}",
    )


async def _notify_changed(db: AsyncSession, trip: Trip, changes: list[tuple[str, str]]) -> None:
    if not changes or trip.driver_id is None or trip.status in _SETTLED:
        return
    body = [f"{_trip_label(trip)} изменён:"]
    body += [f"• {label}: {value}" for label, value in changes]
    await send_driver_message(
        db,
        org_id=trip.org_id,
        driver_id=trip.driver_id,
        truck_id=trip.truck_id,
        kind=DriverMessageKind.trip_changed,
        title="✏️ Изменения в рейсе",
        body="\n".join(body),
    )


async def notify_trip_assigned_background(trip_id: uuid.UUID) -> None:
    try:
        async with SessionLocal() as db:
            trip = await db.get(Trip, trip_id)
            if trip is not None:
                await _notify_assigned(db, trip)
    except Exception:  # noqa: BLE001 — background task, nothing to propagate to
        logger.exception("driver_notice_assigned_failed", trip_id=str(trip_id))


async def notify_trip_changed_background(trip_id: uuid.UUID, changes: list[tuple[str, str]]) -> None:
    try:
        async with SessionLocal() as db:
            trip = await db.get(Trip, trip_id)
            if trip is not None:
                await _notify_changed(db, trip, changes)
    except Exception:  # noqa: BLE001
        logger.exception("driver_notice_changed_failed", trip_id=str(trip_id))


# ── Reminders ────────────────────────────────────────────────────────────


async def _send(db: AsyncSession, **kwargs) -> bool:
    return await send_driver_message(db, **kwargs) is not None


async def _loading_reminders(db: AsyncSession, now: datetime) -> int:
    local_now = now.astimezone(report_tz())
    today = local_now.date()
    rows = (
        await db.execute(
            select(Trip).where(
                Trip.driver_id.is_not(None),
                Trip.scheduled_start.is_not(None),
                Trip.status.in_(_NOT_STARTED),
                Trip.scheduled_start >= now - timedelta(hours=12),
                Trip.scheduled_start <= now + timedelta(days=2),
            )
        )
    ).scalars().all()

    sent = 0
    for trip in rows:
        day = _local_date(trip.scheduled_start)
        if day == today + timedelta(days=1) and local_now.hour >= EVENING_BEFORE_HOUR:
            when, stage = "Завтра", "d1"
        elif day == today and local_now.hour >= MORNING_OF_HOUR:
            when, stage = "Сегодня", "d0"
        else:
            continue
        lines = [f"{when} погрузка — {_trip_label(trip)}."]
        if trip.loading_address:
            lines.append(f"Адрес: {_format_value('loading_address', trip.loading_address)}")
        if trip.loading_contact:
            lines.append(f"Контакты: {_format_value('loading_contact', trip.loading_contact)}")
        lines.append("Не забудьте фото груза при погрузке и включённую геолокацию.")
        sent += await _send(
            db,
            org_id=trip.org_id,
            driver_id=trip.driver_id,
            truck_id=trip.truck_id,
            kind=DriverMessageKind.loading_reminder,
            title=f"📅 {when} погрузка",
            body="\n".join(lines),
            # The date is in the key: a load moved to another day is reminded
            # about again.
            dedupe_key=f"loading_{stage}:{trip.id}:{day.isoformat()}",
        )
    return sent


async def _cmr_reminders(db: AsyncSession, now: datetime) -> int:
    has_cmr = exists().where(
        TripDocument.trip_id == Trip.id, func.lower(TripDocument.category) == "cmr"
    )
    rows = (
        await db.execute(
            select(Trip).where(
                Trip.driver_id.is_not(None),
                Trip.status == TripStatus.delivered,
                Trip.delivered_at.is_not(None),
                Trip.delivered_at <= now - CMR_GRACE,
                Trip.delivered_at >= now - CMR_WINDOW,
                ~has_cmr,
            )
        )
    ).scalars().all()

    sent = 0
    for trip in rows:
        sent += await _send(
            db,
            org_id=trip.org_id,
            driver_id=trip.driver_id,
            truck_id=trip.truck_id,
            kind=DriverMessageKind.cmr_reminder,
            title="📄 Загрузите CMR",
            body=(
                f"{_trip_label(trip)} доставлен, но CMR ещё не загружен. "
                "Сфотографируйте CMR в хорошем качестве и загрузите в приложении: "
                "«Рейсы» → рейс → «Документы»."
            ),
            dedupe_key=f"cmr:{trip.id}",
        )
    return sent


def _current_drivers_query():
    """(truck_id, driver_id, org_id) for every active assignment of an active driver."""
    return (
        select(DriverAssignment.truck_id, Driver.id, Driver.org_id)
        .join(Driver, Driver.id == DriverAssignment.driver_id)
        .where(DriverAssignment.unassigned_at.is_(None), Driver.status == DriverStatus.active)
    )


async def _maintenance_reminders(db: AsyncSession, now: datetime) -> int:
    today = _local_date(now)
    assigned = _current_drivers_query().subquery()
    rows = (
        await db.execute(
            select(ServiceInterval, Truck.plate_number, Truck.mileage, assigned.c.id, assigned.c.org_id)
            .join(Truck, Truck.id == ServiceInterval.truck_id)
            .join(assigned, assigned.c.truck_id == Truck.id)
            .where(ServiceInterval.status != ServiceStatus.completed, Truck.is_enabled.is_(True))
        )
    ).all()

    sent = 0
    for si, plate, mileage, driver_id, org_id in rows:
        km = float(mileage or 0)
        next_km = float(si.next_service_mileage) if si.next_service_mileage is not None else None
        overdue = (si.next_service_date is not None and today >= si.next_service_date) or (
            next_km is not None and km >= next_km
        )
        due_soon = (si.next_service_date is not None and today + timedelta(days=DUE_SOON_DAYS) >= si.next_service_date) or (
            next_km is not None and km + DUE_SOON_KM >= next_km
        )
        if not (overdue or due_soon):
            continue

        service = _SERVICE_RU.get(si.service_type, "ТО")
        target = []
        if si.next_service_date:
            target.append(f"до {si.next_service_date.strftime('%d.%m.%Y')}")
        if next_km is not None:
            target.append(f"на {int(next_km):,} км".replace(",", " "))
        stage = "overdue" if overdue else "soon"
        title = f"🔧 {service}: просрочено" if overdue else f"🔧 Скоро {service.lower()}"
        body = (
            f"{plate}: {service.lower()} {'просрочена' if overdue else 'нужна'} ({', '.join(target)}). "
            "Свяжитесь с диспетчером, чтобы согласовать время сервиса."
        )
        # The interval's own target is in the key: after the service is done
        # and the next one is set, that one is announced afresh.
        target_key = f"{si.next_service_date}:{next_km}"
        sent += await _send(
            db,
            org_id=org_id,
            driver_id=driver_id,
            truck_id=si.truck_id,
            kind=DriverMessageKind.maintenance_due,
            title=title,
            body=body,
            dedupe_key=f"maintenance_{stage}:{si.id}:{target_key}",
        )
    return sent


def _expiry_bucket(days_left: int) -> str | None:
    if days_left <= 0:
        return "expired"
    for bucket in sorted(EXPIRY_BUCKETS):
        if days_left <= bucket:
            return str(bucket)
    return None


def _expiry_text(what: str, expiry: date, days_left: int) -> tuple[str, str]:
    if days_left <= 0:
        return f"⛔ {what}: срок истёк", f"{what} — срок истёк {expiry.strftime('%d.%m.%Y')}. Срочно сообщите диспетчеру."
    return (
        f"⚠️ {what}: осталось {days_left} дн.",
        f"{what} действует до {expiry.strftime('%d.%m.%Y')} (осталось {days_left} дн.). Позаботьтесь о продлении заранее.",
    )


async def _document_reminders(db: AsyncSession, now: datetime) -> int:
    today = _local_date(now)
    horizon = today + timedelta(days=max(EXPIRY_BUCKETS))
    sent = 0

    drivers = (
        await db.execute(
            select(Driver).where(
                Driver.status == DriverStatus.active,
                Driver.license_expiry.is_not(None),
                Driver.license_expiry <= horizon,
                Driver.license_expiry >= today - timedelta(days=1),
            )
        )
    ).scalars().all()
    for driver in drivers:
        days_left = (driver.license_expiry - today).days
        bucket = _expiry_bucket(days_left)
        if bucket is None:
            continue
        title, body = _expiry_text("Водительское удостоверение", driver.license_expiry, days_left)
        sent += await _send(
            db,
            org_id=driver.org_id,
            driver_id=driver.id,
            kind=DriverMessageKind.document_expiry,
            title=title,
            body=body,
            dedupe_key=f"license:{driver.id}:{driver.license_expiry.isoformat()}:{bucket}",
        )

    assigned = _current_drivers_query().subquery()
    trucks = (
        await db.execute(
            select(Truck, assigned.c.id)
            .join(assigned, assigned.c.truck_id == Truck.id)
            .where(
                Truck.is_enabled.is_(True),
                Truck.insurance_expiry.is_not(None),
                Truck.insurance_expiry <= horizon,
                Truck.insurance_expiry >= today - timedelta(days=1),
            )
        )
    ).all()
    for truck, driver_id in trucks:
        days_left = (truck.insurance_expiry - today).days
        bucket = _expiry_bucket(days_left)
        if bucket is None:
            continue
        title, body = _expiry_text(f"Страховка {truck.plate_number}", truck.insurance_expiry, days_left)
        sent += await _send(
            db,
            org_id=truck.org_id,
            driver_id=driver_id,
            truck_id=truck.id,
            kind=DriverMessageKind.document_expiry,
            title=title,
            body=body,
            dedupe_key=f"insurance:{truck.id}:{driver_id}:{truck.insurance_expiry.isoformat()}:{bucket}",
        )
    return sent


async def run(db: AsyncSession, *, now: datetime | None = None) -> int:
    """Every reminder, across every organization. Returns messages sent. Never raises."""
    now = now or datetime.now(timezone.utc)
    sent = 0
    for reminder in (_loading_reminders, _cmr_reminders, _maintenance_reminders, _document_reminders):
        try:
            sent += await reminder(db, now)
        except Exception:  # noqa: BLE001 — one broken reminder must not hide the rest
            logger.exception("driver_reminder_failed", reminder=reminder.__name__)
            try:
                await db.rollback()
            except Exception:  # noqa: BLE001
                logger.exception("driver_reminder_rollback_failed")
    logger.info("driver_reminders_done", sent=sent)
    return sent
