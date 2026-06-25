"""AI-powered fleet report generation.

Gathers structured data from the database for a given report type and
asks an OpenAI-compatible chat completion API to produce a localized
markdown report.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.drivers import Driver, DriverAssignment
from app.models.maintenance import FuelLog, MaintenanceRecord
from app.models.trucks import Truck

ReportType = Literal["fuel", "maintenance", "trucks", "drivers", "full"]
ReportLanguage = Literal["en", "ru", "uz"]

LANGUAGE_NAMES: dict[ReportLanguage, str] = {
    "en": "English",
    "ru": "Russian",
    "uz": "Uzbek",
}


@dataclass(frozen=True)
class GeneratedReport:
    content: str
    filename: str


async def _gather_fuel(db: AsyncSession, start: datetime, org_id) -> dict[str, Any]:
    rows = (
        await db.execute(
            select(
                FuelLog.truck_id,
                func.sum(FuelLog.liters).label("liters"),
                func.sum(FuelLog.total_cost).label("cost"),
                func.count(FuelLog.id).label("fills"),
                func.avg(FuelLog.cost_per_liter).label("avg_price"),
            )
            .join(Truck, Truck.id == FuelLog.truck_id)
            .where(FuelLog.filled_at >= start, Truck.org_id == org_id)
            .group_by(FuelLog.truck_id)
        )
    ).all()
    truck_names = dict(
        (str(t.id), f"{t.name} ({t.plate_number})")
        for t in (await db.execute(select(Truck).where(Truck.org_id == org_id))).scalars()
    )
    return {
        "by_truck": [
            {
                "truck": truck_names.get(str(r.truck_id), str(r.truck_id)),
                "liters": float(r.liters or 0),
                "total_cost": float(r.cost or 0),
                "fill_ups": int(r.fills or 0),
                "avg_price_per_liter": float(r.avg_price or 0),
            }
            for r in rows
        ]
    }


async def _gather_maintenance(db: AsyncSession, start: datetime, org_id) -> dict[str, Any]:
    rows = (
        await db.execute(
            select(MaintenanceRecord)
            .join(Truck, Truck.id == MaintenanceRecord.truck_id)
            .where(MaintenanceRecord.performed_at >= start.date(), Truck.org_id == org_id)
        )
    ).scalars().all()
    truck_names = dict(
        (str(t.id), f"{t.name} ({t.plate_number})")
        for t in (await db.execute(select(Truck).where(Truck.org_id == org_id))).scalars()
    )
    return {
        "records": [
            {
                "truck": truck_names.get(str(r.truck_id), str(r.truck_id)),
                "service_type": r.service_type.value if hasattr(r.service_type, "value") else str(r.service_type),
                "performed_at": r.performed_at.isoformat(),
                "cost": float(r.cost or 0),
                "description": r.description or "",
                "performed_by": r.performed_by or "",
            }
            for r in rows
        ]
    }


async def _gather_trucks(db: AsyncSession, org_id) -> dict[str, Any]:
    trucks = (await db.execute(select(Truck).where(Truck.org_id == org_id))).scalars().all()
    assignments = (
        await db.execute(
            select(DriverAssignment.truck_id, Driver.name)
            .join(Driver, Driver.id == DriverAssignment.driver_id)
            .where(DriverAssignment.unassigned_at.is_(None), Driver.org_id == org_id)
        )
    ).all()
    drivers_by_truck: dict[str, list[str]] = {}
    for truck_id, name in assignments:
        drivers_by_truck.setdefault(str(truck_id), []).append(name)

    return {
        "trucks": [
            {
                "name": t.name,
                "plate": t.plate_number,
                "status": t.status.value if hasattr(t.status, "value") else str(t.status),
                "drivers": drivers_by_truck.get(str(t.id), []),
            }
            for t in trucks
        ]
    }


async def _gather_drivers(db: AsyncSession, org_id) -> dict[str, Any]:
    drivers = (await db.execute(select(Driver).where(Driver.org_id == org_id))).scalars().all()
    truck_names = dict(
        (str(t.id), f"{t.name} ({t.plate_number})")
        for t in (await db.execute(select(Truck).where(Truck.org_id == org_id))).scalars()
    )
    active_assignments = (
        await db.execute(
            select(DriverAssignment.driver_id, DriverAssignment.truck_id)
            .join(Driver, Driver.id == DriverAssignment.driver_id)
            .where(DriverAssignment.unassigned_at.is_(None), Driver.org_id == org_id)
        )
    ).all()
    truck_by_driver: dict[str, str] = {
        str(d_id): truck_names.get(str(t_id), "") for d_id, t_id in active_assignments
    }
    return {
        "drivers": [
            {
                "name": d.name,
                "status": d.status.value if hasattr(d.status, "value") else str(d.status),
                "license_number": d.license_number,
                "current_truck": truck_by_driver.get(str(d.id), ""),
            }
            for d in drivers
        ]
    }


async def _gather_data(
    db: AsyncSession, report_type: ReportType, days: int, org_id
) -> dict[str, Any]:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    payload: dict[str, Any] = {
        "report_type": report_type,
        "window_days": days,
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
    }
    if report_type in ("fuel", "full"):
        payload["fuel"] = await _gather_fuel(db, start, org_id)
    if report_type in ("maintenance", "full"):
        payload["maintenance"] = await _gather_maintenance(db, start, org_id)
    if report_type in ("trucks", "full"):
        payload["trucks"] = await _gather_trucks(db, org_id)
    if report_type in ("drivers", "full"):
        payload["drivers"] = await _gather_drivers(db, org_id)
    return payload


def _build_prompt(data: dict[str, Any], language: ReportLanguage) -> tuple[str, str]:
    lang_name = LANGUAGE_NAMES[language]
    system = (
        f"You are a fleet operations analyst. Produce a clear, well-structured markdown "
        f"report written entirely in {lang_name}. Use headings, bullet lists, and tables "
        f"where appropriate. Highlight notable trends, costs, and risks. Do not invent "
        f"data — only summarize what is provided in the JSON input."
    )
    user = (
        f"Generate a fleet '{data['report_type']}' report covering the last "
        f"{data['window_days']} days. The full data is below as JSON. Write the entire "
        f"response in {lang_name}.\n\nDATA:\n```json\n"
        f"{json.dumps(data, ensure_ascii=False, indent=2)}\n```"
    )
    return system, user


async def _call_ai(system: str, user: str) -> str:
    if not settings.ai_api_key:
        raise RuntimeError("AI_API_KEY is not configured on the server")

    url = f"{settings.ai_base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.ai_api_key}",
        "Content-Type": "application/json",
    }
    body = {
        "model": settings.ai_model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.3,
    }
    async with httpx.AsyncClient(timeout=90.0) as client:
        res = await client.post(url, headers=headers, json=body)
        res.raise_for_status()
        data = res.json()
    return data["choices"][0]["message"]["content"]


async def generate_report(
    db: AsyncSession,
    report_type: ReportType,
    language: ReportLanguage,
    days: int,
    org_id,
) -> GeneratedReport:
    data = await _gather_data(db, report_type, days, org_id)
    system, user = _build_prompt(data, language)
    content = await _call_ai(system, user)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    filename = f"fleet-{report_type}-{language}-{timestamp}.md"
    return GeneratedReport(content=content, filename=filename)
