"""Document & service expiry reminders.

Surfaces things that cost a fleet money (or a fine) when they lapse:

* **Driver licence expiry** — driving on an expired licence is an instant fine
  and an insurance void in Uzbekistan.
* **Service intervals due** — maintenance whose next-service date/mileage is
  near or passed (complements the overdue-status job with a "due soon" view).

Everything is scoped per organization. The scheduler job logs one structured
warning per expiring item so owners have an audit trail even without opening the
UI; the API endpoint returns the same data for the dashboard.
"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SessionLocal
from app.core.logging import logger
from app.models.drivers import Driver
from app.models.enums import ServiceStatus
from app.models.maintenance import ServiceInterval
from app.models.trucks import Truck

DEFAULT_DAYS_AHEAD = 30


async def upcoming_expiries(db: AsyncSession, org_id, days_ahead: int = DEFAULT_DAYS_AHEAD) -> dict:
    """Licence + service items expiring within ``days_ahead`` for one org."""
    today = date.today()
    horizon = today + timedelta(days=days_ahead)

    # Driver licences expiring (or already expired).
    licence_rows = (
        await db.execute(
            select(Driver)
            .where(
                Driver.org_id == org_id,
                Driver.license_expiry.is_not(None),
                Driver.license_expiry <= horizon,
            )
            .order_by(Driver.license_expiry)
        )
    ).scalars().all()

    licences = [
        {
            "driver_id": str(d.id),
            "driver_name": d.name,
            "license_number": d.license_number,
            "license_expiry": d.license_expiry.isoformat() if d.license_expiry else None,
            "days_left": (d.license_expiry - today).days if d.license_expiry else None,
            "expired": bool(d.license_expiry and d.license_expiry < today),
        }
        for d in licence_rows
    ]

    # Service intervals due soon or overdue (scoped via the owning truck).
    service_rows = (
        await db.execute(
            select(ServiceInterval, Truck)
            .join(Truck, Truck.id == ServiceInterval.truck_id)
            .where(
                Truck.org_id == org_id,
                (
                    (ServiceInterval.next_service_date.is_not(None) & (ServiceInterval.next_service_date <= horizon))
                    | (ServiceInterval.status == ServiceStatus.overdue)
                ),
            )
            .order_by(ServiceInterval.next_service_date)
        )
    ).all()

    services = [
        {
            "truck_id": str(t.id),
            "truck_name": t.name,
            "plate_number": t.plate_number,
            "service_type": si.service_type.value if hasattr(si.service_type, "value") else str(si.service_type),
            "next_service_date": si.next_service_date.isoformat() if si.next_service_date else None,
            "days_left": (si.next_service_date - today).days if si.next_service_date else None,
            "status": si.status.value if hasattr(si.status, "value") else str(si.status),
        }
        for si, t in service_rows
    ]

    return {
        "days_ahead": days_ahead,
        "license_expiries": licences,
        "service_due": services,
        "total": len(licences) + len(services),
    }


async def check_document_expiries() -> None:
    """Scheduler job: log a warning per soon-expiring driver licence, all orgs.

    Idempotent (read-only + log). Service-interval overdue logging is already
    handled by ``check_overdue_maintenance``; this focuses on driver documents,
    which have no other watchdog.
    """
    try:
        async with SessionLocal() as db:
            today = date.today()
            horizon = today + timedelta(days=DEFAULT_DAYS_AHEAD)
            rows = (
                await db.execute(
                    select(Driver).where(
                        Driver.license_expiry.is_not(None),
                        Driver.license_expiry <= horizon,
                    )
                )
            ).scalars().all()
            for d in rows:
                logger.warning(
                    "driver_license_expiring",
                    org_id=str(d.org_id),
                    driver_id=str(d.id),
                    driver_name=d.name,
                    license_number=d.license_number,
                    license_expiry=d.license_expiry.isoformat() if d.license_expiry else None,
                    days_left=(d.license_expiry - today).days if d.license_expiry else None,
                    expired=bool(d.license_expiry and d.license_expiry < today),
                )
            logger.info("document_expiry_check_done", flagged=len(rows), as_of=str(today))
    except Exception:  # noqa: BLE001 — never let a job crash the scheduler
        logger.exception("document_expiry_check_failed")
