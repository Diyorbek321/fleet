from __future__ import annotations

from datetime import date, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.maintenance import ServiceInterval
from app.models.trucks import Truck
from app.models.enums import ServiceStatus

DUE_SOON_DAYS = 7
DUE_SOON_KM = 500

async def refresh_service_statuses(db: AsyncSession) -> int:
    """Recomputes service interval statuses.

    Rules:
    - overdue if today >= next_service_date OR truck.mileage >= next_service_mileage
    - due soon if within 7 days or 500 km
    """
    today = date.today()
    updated = 0

    res = await db.execute(select(ServiceInterval))
    intervals = res.scalars().all()

    for si in intervals:
        # fetch truck mileage
        t_res = await db.execute(select(Truck).where(Truck.id == si.truck_id))
        truck = t_res.scalar_one_or_none()
        mileage = float(truck.mileage) if truck else 0.0

        overdue = False
        due_soon = False

        if si.next_service_date and today >= si.next_service_date:
            overdue = True
        if si.next_service_mileage is not None and mileage >= float(si.next_service_mileage):
            overdue = True

        if not overdue:
            if si.next_service_date and today + timedelta(days=DUE_SOON_DAYS) >= si.next_service_date:
                due_soon = True
            if si.next_service_mileage is not None and mileage + DUE_SOON_KM >= float(si.next_service_mileage):
                due_soon = True

        # We only store scheduled/overdue/completed in schema;
        # represent due_soon as scheduled but expose a computed flag in reminders endpoint.
        new_status = ServiceStatus.overdue if overdue else ServiceStatus.scheduled

        if si.status != new_status:
            si.status = new_status
            updated += 1

    await db.commit()
    return updated
