"""Owner alerts for documents and services that are running out of time.

The facts were already there. :func:`app.services.reminders.upcoming_expiries`
has been computing expiring driver licences and due service intervals for the
dashboard, and the scheduler has been writing one ``logger.warning`` per item
since the beginning — into a log nobody reads. This module is the last hop: the
same org-scoped query, turned into a message the owner actually receives.

**Proximity is the severity.** A licence expiring in a month and a licence that
expired last week are the same row with a different date. Flattening them onto
one level either pages an owner about paperwork or buries a truck that is
illegal to drive today, so there are three buckets — 30 days out is ``info``,
the last week is ``warning``, past the date is ``critical`` — and the bucket is
part of the dedupe key. One licence therefore produces three messages on its way
out instead of one on the day it first crosses the horizon.

**The TTL is what stops the nagging.** ``notification_log`` suppresses a repeat
of the same key, so that key's TTL decides how often one fact may be restated.
Every bucket's TTL is longer than the bucket is wide, which makes "once per
bucket" the natural outcome rather than something this module has to police.
``critical`` is the deliberate exception: an expired document never leaves its
bucket, so its key would otherwise be permanent and the owner would be told
once and never again.
"""
from __future__ import annotations

import html
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger
from app.models.drivers import Driver
from app.models.enums import DriverStatus, ServiceStatus
from app.models.organizations import Organization
from app.models.owner_alerts import SEVERITY_RANK, TelegramAccount
from app.services.owner_alerts.bus import Alert, AlertKind, AlertSeverity, notify_owner
from app.services.reminders import DEFAULT_DAYS_AHEAD, upcoming_expiries

# The last week before a date is when a fleet can still act — order the part,
# book the service, start the licence renewal. Inside it the alert stops being
# informational.
WARNING_DAYS = 7

# One message per bucket, not one per tick. A TTL shorter than its bucket is
# wide would restate the same sentence daily until the date moved the item on.
#
#   info      spans days 30..8 — at most 23 days in the bucket, so 30 days of
#             suppression yields exactly one "this is coming" message.
#   warning   spans days 7..0 — 8 days of suppression, one message.
#   critical  never ends. An expired licence is expired forever and its bucket
#             can no longer change, so this is the only TTL that is a chosen
#             re-fire rather than a ceiling. Weekly: often enough that an
#             unrenewed document stays on the owner's desk, rare enough that
#             the fix is renewing it rather than muting the bot.
#
# All three sit inside ``prune_notification_log``'s 30-day sweep, which only
# ever drops rows past the point their key is still consulted.
_BUCKET_TTL_HOURS: dict[AlertSeverity, int] = {
    AlertSeverity.info: 24 * 30,
    AlertSeverity.warning: 24 * 8,
    AlertSeverity.critical: 24 * 7,
}

# A fleet that has never had this feature has a backlog: every expired document
# and every overdue interval it has accumulated, all newly reportable on the
# first tick after an owner links their chat. Two hundred messages in one burst
# is how the bot gets muted on day one, so a run hands over a readable batch and
# the next run continues — nothing is lost, because an item that was not sent
# was not recorded either.
_MAX_ALERTS_PER_ORG_PER_RUN = 12

_SERVICE_LABELS_UZ: dict[str, str] = {
    "oil_change": "Moy almashtirish",
    "tire_rotation": "G'ildiraklarni almashtirish",
    "brake_inspection": "Tormoz tekshiruvi",
    "engine_service": "Dvigatel xizmati",
    "transmission": "Transmissiya",
    "general": "Umumiy texnik xizmat",
}


def _esc(value: Any) -> str:
    """Escape a value for an alert body.

    ``quote=False`` for the same reason the bus escapes titles that way: an
    apostrophe is a letter in half the Uzbek copy here ("G'ildirak", "o'tgan"),
    and ``&#x27;`` is what an owner sees anywhere the HTML is not rendered.
    """
    return html.escape("" if value is None else str(value), quote=False)


# ── Buckets ──────────────────────────────────────────────────────────────


def severity_for(days_left: int | None, *, already_late: bool) -> AlertSeverity:
    """Which bucket an item falls in, from its distance to the date.

    ``already_late`` carries what the date alone cannot: a service interval can
    be overdue on mileage while its planned date is still weeks away.
    """
    if already_late or (days_left is not None and days_left < 0):
        return AlertSeverity.critical
    if days_left is None:
        return AlertSeverity.warning
    if days_left <= WARNING_DAYS:
        return AlertSeverity.warning
    return AlertSeverity.info


def dedupe_ttl_hours(severity: AlertSeverity) -> int:
    return _BUCKET_TTL_HOURS.get(severity, 24)


# ── Message bodies ───────────────────────────────────────────────────────


def _remaining_line(days_left: int | None) -> str:
    if days_left is None:
        return ""
    if days_left < 0:
        return f"<b>Muddati o'tgan:</b> {abs(days_left)} kun"
    if days_left == 0:
        return "<b>Muddat:</b> bugun tugaydi"
    return f"<b>Qolgan:</b> {days_left} kun"


def _licence_alert(row: dict, severity: AlertSeverity) -> Alert:
    driver_name = row.get("driver_name") or "—"
    verb = "tugagan" if severity is AlertSeverity.critical else "tugaydi"

    lines = [
        f"<b>Guvohnoma:</b> {_esc(row.get('license_number') or '—')}",
        f"<b>Amal qilish muddati:</b> {_esc(row.get('license_expiry') or '—')}",
    ]
    remaining = _remaining_line(row.get("days_left"))
    if remaining:
        lines.append(remaining)
    if severity is AlertSeverity.critical:
        lines.append("Muddati o'tgan guvohnoma bilan yo'lga chiqish — jarima va sug'urtasiz reys.")

    driver_id = row.get("driver_id")
    return Alert(
        kind=AlertKind.document_expiry,
        severity=severity,
        title=f"Haydovchi guvohnomasi muddati {verb} — {driver_name}",
        body="\n".join(lines),
        # The bucket is in the key on purpose: it is what turns one licence into
        # three messages as it approaches instead of one and then silence.
        dedupe_key=f"expiry:licence:{driver_id}:{severity.value}",
        dedupe_ttl_hours=dedupe_ttl_hours(severity),
        path=f"/drivers/{driver_id}" if driver_id else None,
    )


def _service_alert(row: dict, severity: AlertSeverity) -> Alert:
    plate = row.get("plate_number") or "—"
    service_type = str(row.get("service_type") or "")
    label = _SERVICE_LABELS_UZ.get(service_type, service_type or "—")
    verb = "o'tgan" if severity is AlertSeverity.critical else "yaqinlashdi"

    lines = [
        f"<b>Mashina:</b> {_esc(row.get('truck_name') or '—')} ({_esc(plate)})",
        f"<b>Xizmat turi:</b> {_esc(label)}",
    ]
    planned = row.get("next_service_date")
    if planned:
        lines.append(f"<b>Rejalashtirilgan sana:</b> {_esc(planned)}")
    elif severity is AlertSeverity.critical:
        # No date and still overdue means the mileage threshold tripped it.
        lines.append("<b>Sabab:</b> probeg bo'yicha muddati o'tgan")
    remaining = _remaining_line(row.get("days_left"))
    if remaining:
        lines.append(remaining)

    truck_id = row.get("truck_id")
    return Alert(
        # There is no "maintenance due soon" kind, and inventing one would split
        # the mute switch an owner reaches for: they want the maintenance
        # channel louder or quieter, not its two halves separately.
        kind=AlertKind.maintenance_overdue,
        severity=severity,
        title=f"Texnik xizmat muddati {verb} — {plate}",
        body="\n".join(lines),
        # (truck, service_type) is unique by constraint, so it names the fact as
        # stably as the interval's own id would.
        dedupe_key=f"expiry:service:{truck_id}:{service_type}:{severity.value}",
        dedupe_ttl_hours=dedupe_ttl_hours(severity),
        path=f"/trucks/{truck_id}" if truck_id else None,
    )


# ── Collecting one organization's due items ──────────────────────────────


@dataclass(frozen=True)
class _Due:
    """One reportable item, kept with what it takes to order the batch."""

    severity: AlertSeverity
    days_left: int | None
    alert: Alert

    @property
    def urgency(self) -> tuple[int, int]:
        # Most severe first, then soonest first. A missing date only happens on
        # an item that is already late, so it sorts ahead of every real number.
        soonest = self.days_left if self.days_left is not None else -10**6
        return (-SEVERITY_RANK[self.severity], soonest)


async def _inactive_driver_ids(db: AsyncSession, org_id: uuid.UUID) -> set[str]:
    """Drivers the fleet has stopped employing.

    Their licences expire too, and nobody renews them — which under a
    ``critical`` bucket means a weekly message about a person who left the
    company, forever. ``status`` is the only signal the schema has for that, so
    it is the one used. The reminders *panel* still lists them, deliberately:
    seeing a stale row is harmless, being messaged about it every week is not.
    """
    rows = await db.execute(
        select(Driver.id).where(Driver.org_id == org_id, Driver.status == DriverStatus.inactive)
    )
    return {str(driver_id) for driver_id in rows.scalars().all()}


def _collect(data: dict, skip_driver_ids: set[str]) -> list[_Due]:
    """Turn one org's reminder payload into an ordered list of alerts."""
    items: list[_Due] = []

    for row in data.get("license_expiries") or []:
        if str(row.get("driver_id")) in skip_driver_ids:
            continue
        severity = severity_for(row.get("days_left"), already_late=bool(row.get("expired")))
        items.append(_Due(severity, row.get("days_left"), _licence_alert(row, severity)))

    for row in data.get("service_due") or []:
        overdue = row.get("status") == ServiceStatus.overdue.value
        severity = severity_for(row.get("days_left"), already_late=overdue)
        items.append(_Due(severity, row.get("days_left"), _service_alert(row, severity)))

    items.sort(key=lambda item: item.urgency)
    return items


async def _org_ids_with_a_listening_chat(db: AsyncSession) -> list[uuid.UUID]:
    """Organizations worth evaluating at all.

    The bus drops an alert for an org with no activated chat without recording
    it, so scanning every other tenant's drivers and trucks each hour buys
    nothing. Suspended organizations are excluded for a different reason: an org
    with ``is_active`` false is one we have stopped serving, and it should not
    keep receiving messages about its fleet.
    """
    rows = await db.execute(
        select(TelegramAccount.org_id)
        .join(Organization, Organization.id == TelegramAccount.org_id)
        .where(
            TelegramAccount.is_active.is_(True),
            TelegramAccount.chat_id.is_not(None),
            Organization.is_active.is_(True),
        )
        .distinct()
    )
    return list(rows.scalars().all())


async def _run_org(db: AsyncSession, org_id: uuid.UUID) -> int:
    data = await upcoming_expiries(db, org_id, DEFAULT_DAYS_AHEAD)
    due = _collect(data, await _inactive_driver_ids(db, org_id))

    sent = 0
    for item in due:
        # Counted on delivery, not on attempt: a batch where the first twelve
        # items are already deduped must still reach the thirteenth, or a
        # standing backlog would permanently hide everything behind it.
        if sent >= _MAX_ALERTS_PER_ORG_PER_RUN:
            break
        sent += await notify_owner(db, org_id, item.alert)
    return sent


async def run(db: AsyncSession) -> int:
    """Evaluate document and service expiry across every organization and notify.

    Returns the number of alerts sent. Never raises — one organization with
    unreadable data must not cost every other organization its tick.
    """
    try:
        org_ids = await _org_ids_with_a_listening_chat(db)
    except Exception:  # noqa: BLE001
        logger.exception("expiry_watch_scan_failed")
        return 0

    total = 0
    for org_id in org_ids:
        try:
            total += await _run_org(db, org_id)
        except Exception:  # noqa: BLE001
            logger.exception("expiry_watch_org_failed", org_id=str(org_id))
            try:
                await db.rollback()  # leave the session usable for the next org
            except Exception:  # noqa: BLE001
                logger.exception("expiry_watch_rollback_failed", org_id=str(org_id))

    logger.info("expiry_watch_done", orgs=len(org_ids), alerts_sent=total)
    return total
