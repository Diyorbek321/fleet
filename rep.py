import asyncio, sys
sys.path.insert(0, "/app")
from datetime import date
from sqlalchemy import select
from app.core.database import SessionLocal
from app.models.organizations import Organization
from app.services.period_reports import build_period_report, resolve_period
from app.services.country_expenses import build_country_expense_report
import demo_data_uz as D

async def main():
    async with SessionLocal() as db:
        org = (await db.execute(select(Organization).where(Organization.name == D.ORG_NAME))).scalar_one()
        for off in (1, 0):
            p = resolve_period("month", off, today=date(2026, 9, 15))
            r = await build_period_report(db, org.id, p)
            lpk = (r.fuel_liters / r.distance_km * 100) if r.distance_km > 1 else None
            print(f"--- {p.label} ({p.start} .. {p.end}) ---")
            print(f"  yetkazilgan reys : {r.trips_delivered}   jarayonda: {r.trips_in_progress}")
            print(f"  daromad          : {r.revenue:,.0f}")
            print(f"  yoqilgi          : {r.fuel_liters:,.0f} l / {r.fuel_cost:,.0f}")
            print(f"  masofa           : {r.distance_km:,.0f} km"
                  + (f"   -> {lpk:.1f} L/100km" if lpk else ""))
            print(f"  xarajat / texnik : {r.expense_cost:,.0f} / {r.maintenance_cost:,.0f}")
            print(f"  qatorlar         : {len(r.trucks)} mashina, {len(r.drivers)} haydovchi")
            print(f"  partial          : {getattr(r, 'partial', 'n/a')}  fills={r.fills}  trucks_moved={r.trucks_moved}")
            c = await build_country_expense_report(db, org.id, start=p.start, end=p.end)
            print(f"  mamlakat hisobot : {len(c.trips)} reys")
asyncio.run(main())
