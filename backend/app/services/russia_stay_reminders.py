"""Reminders before a driver's 90 days in Russia run out.

At 15, 7 and 3 days before the last legal day the driver gets a push and the
company's owner chats an alert; once past it, both every day until the stay is
closed. Each reminder is keyed on the driver, the deadline and the bucket, so a
fifteen-minute scheduler sends it once — and a deadline the desk moves (a
corrected entry date) is a new deadline that is reminded about afresh.

Sent in daytime only (Tashkent): a push at 00:05 telling a sleeping driver
they have fifteen days is worse than the same push at 08:00.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger
from app.models.driver_messages import DriverMessageKind
from app.models.drivers import Driver
from app.models.owner_alerts import AlertKind, AlertSeverity
from app.models.russia_stays import DriverRussiaStay
from app.services.driver_messages import send_driver_message
from app.services.owner_alerts.bus import Alert, notify_owner
from app.services.period_reports import report_tz
from app.services.russia_stay import StaySummary, reminder_bucket
from app.services.russia_stay_records import local_today, summary_for

DAY_FROM_HOUR = 8
DAY_TO_HOUR = 20


def _driver_text(s: StaySummary) -> tuple[str, str]:
    deadline = s.must_leave_by.strftime("%d.%m.%Y") if s.must_leave_by else "—"
    if s.overstay_days > 0 or (s.days_to_leave or 0) < 0:
        return (
            "⛔ Срок пребывания в РФ превышен",
            f"Вы в России {s.day_of_stay}-й день, лимит 90 дней за 180 превышен "
            f"на {s.overstay_days} дн. Срочно свяжитесь с диспетчером.",
        )
    return (
        f"⚠️ РФ: осталось {s.days_to_leave} дн.",
        f"Вы в России {s.day_of_stay}-й день. Выехать нужно не позднее {deadline} "
        f"(осталось {s.days_to_leave} дн.) — лимит 90 дней за 180.",
    )


def _owner_alert(driver_id, driver_name: str, s: StaySummary, bucket: str, today_key: str) -> Alert:
    deadline = s.must_leave_by.strftime("%d.%m.%Y") if s.must_leave_by else "—"
    over = bucket == "over"
    return Alert(
        kind=AlertKind.document_expiry,
        severity=AlertSeverity.critical if over or bucket == "3" else AlertSeverity.warning,
        title=(
            f"Превышен срок пребывания в РФ — {driver_name}"
            if over
            else f"РФ: {driver_name} — осталось {s.days_to_leave} дн."
        ),
        body="\n".join(
            [
                f"В России: {s.day_of_stay}-й день (за 180 дней: {s.days_used})",
                f"Выехать до: <b>{deadline}</b>" if not over else f"Превышение: <b>{s.overstay_days} дн.</b>",
            ]
        ),
        dedupe_key=f"russia:{driver_id}:{s.must_leave_by}:{bucket}" + (f":{today_key}" if over else ""),
        dedupe_ttl_hours=20 if over else 24 * 30,
        path=f"/drivers/{driver_id}",
    )


async def run(db: AsyncSession, *, now: datetime | None = None) -> int:
    """Remind every driver now in Russia whose deadline is near. Returns driver pushes sent."""
    now = now or datetime.now(timezone.utc)
    hour = now.astimezone(report_tz()).hour
    if not DAY_FROM_HOUR <= hour < DAY_TO_HOUR:
        return 0
    today = local_today(now)

    rows = (
        await db.execute(
            # Plain columns, not Driver rows: a rollback after one driver's
            # failure expires every loaded instance, and the next driver's
            # attributes must still be readable.
            select(Driver.id, Driver.org_id, Driver.name)
            .join(DriverRussiaStay, DriverRussiaStay.driver_id == Driver.id)
            .where(DriverRussiaStay.left_on.is_(None), DriverRussiaStay.entered_on <= today)
        )
    ).all()

    sent = 0
    for driver_id, org_id, driver_name in rows:
        try:
            summary = await summary_for(db, driver_id, today)
            bucket = reminder_bucket(summary)
            if bucket is None:
                continue
            title, body = _driver_text(summary)
            key = f"russia:{driver_id}:{summary.must_leave_by}:{bucket}"
            if bucket == "over":
                key += f":{today.isoformat()}"
            message = await send_driver_message(
                db,
                org_id=org_id,
                driver_id=driver_id,
                kind=DriverMessageKind.russia_stay,
                title=title,
                body=body,
                dedupe_key=key,
            )
            if message is not None:
                sent += 1
            await notify_owner(db, org_id, _owner_alert(driver_id, driver_name, summary, bucket, today.isoformat()))
        except Exception:  # noqa: BLE001 — one driver's bad record must not cost the rest theirs.
            logger.exception("russia_stay_reminder_failed", driver_id=str(driver_id))
            await db.rollback()
    return sent
