"""Fire the demo tenant's Telegram messages on demand, for the live walkthrough.

Every notification in this product is scheduled: the owner's digest goes out at
07:00, the watchers tick every fifteen minutes, the cargo owner's morning
update is keyed to ``TELEGRAM_DAILY_HOUR_UTC``. That is correct for a customer
and useless in a meeting room, where the message has to arrive while the
prospect is looking at the phone.

This is the presenter's remote control. Each subcommand produces one real
message through the real bus — nothing is faked, nothing is pre-recorded.

    python demo_fire.py status                 # pre-flight: what is actually linked?

    python demo_fire.py owner briefing         # ertalabki xulosa, soat qaramasdan
    python demo_fire.py owner leakage          # yo'qotishlar (yoqilg'i, ruxsatsiz to'xtash)
    python demo_fire.py owner trips            # kechikkan reyslar + holat o'zgarishi
    python demo_fire.py owner expiry           # hujjat va texkо'rik muddatlari
    python demo_fire.py owner cash             # kassa nomuvofiqligi
    python demo_fire.py owner reports          # oylik yopilish — ikkita .xlsx
    python demo_fire.py owner all              # hammasi, ketma-ket

    python demo_fire.py customer daily         # yuk egalariga ertalabki xabar
    python demo_fire.py customer status TR-2026-0021 --status at_border

**Production safety.** This runs against the same database as paying
customers, so two rules are load-bearing:

* the dedupe log is cleared *only* for the demo organization. Clearing it
  globally would re-announce every still-true fact — every overdue service
  interval, every unreconciled trip — to every real customer at once.
* the two org-scoped senders (``customer daily``, ``customer status``) resolve
  subscriptions through the demo org, never through the global query the
  scheduler uses.

The owner watchers themselves are global by design and are left that way: they
are the same sweep the scheduler runs every fifteen minutes, and with the demo
org's log the only one cleared, every other tenant sees a no-op tick.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import delete, select

import demo_data_uz as D
from app.core.config import settings
from app.core.database import SessionLocal
from app.models.enums import TripStatus
from app.models.notifications import TripSubscription
from app.models.organizations import Organization
from app.models.owner_alerts import NotificationLog, TelegramAccount
from app.models.trips import Trip
from app.models.trucks import TruckLocation
from app.services.owner_alerts import briefing as owner_briefing
from app.services.owner_alerts import cash as owner_cash
from app.services.owner_alerts import expiry as owner_expiry
from app.services.owner_alerts import leakage as owner_leakage
from app.services.owner_alerts import reports as owner_reports
from app.services.owner_alerts import trips as owner_trips
from app.services.owner_alerts.bus import notify_owner
from app.services.period_reports import report_tz, resolve_period
from app.services.telegram import format_daily_update, format_status_change, send_message

# Which dedupe rows a subcommand has to clear before its watcher can speak
# again. Keyed by ``AlertKind.value`` because ``NotificationLog.kind`` is a
# plain string column — see the model's note on why.
WATCHERS: dict[str, tuple[object, tuple[str, ...], str]] = {
    "trips": (owner_trips, ("trip_status", "trip_delay"), "reys holati va kechikishlar"),
    "leakage": (owner_leakage, ("leakage",), "yo'qotishlar"),
    "expiry": (owner_expiry, ("document_expiry", "maintenance_overdue"), "muddatlar"),
    "cash": (owner_cash, ("cash_mismatch",), "kassa nomuvofiqligi"),
}


# --------------------------------------------------------------------------- #
# Shared helpers                                                               #
# --------------------------------------------------------------------------- #

async def demo_org(db) -> Organization:
    org = (
        await db.execute(select(Organization).where(Organization.name == D.ORG_NAME))
    ).scalar_one_or_none()
    if org is None:
        raise SystemExit(f"organization {D.ORG_NAME!r} not found — run seed_demo_uz.py first")
    return org


async def clear_dedupe(db, org: Organization, kinds: tuple[str, ...]) -> int:
    """Forget that the demo org was already told these things.

    Scoped to one org id on purpose — see this module's docstring.
    """
    result = await db.execute(
        delete(NotificationLog).where(
            NotificationLog.org_id == org.id, NotificationLog.kind.in_(kinds)
        )
    )
    await db.commit()
    return result.rowcount or 0


def require_telegram() -> None:
    if not settings.telegram_configured:
        raise SystemExit(
            "TELEGRAM_BOT_TOKEN sozlanmagan — xabar yuborib bo'lmaydi.\n"
            "  Backend .env ga TELEGRAM_BOT_TOKEN qo'shing va konteynerni qayta ishga tushiring."
        )


# --------------------------------------------------------------------------- #
# Pre-flight                                                                   #
# --------------------------------------------------------------------------- #

async def cmd_status() -> None:
    """What is actually wired up right now — run this before the meeting."""
    async with SessionLocal() as db:
        org = await demo_org(db)

        accounts = (
            await db.execute(select(TelegramAccount).where(TelegramAccount.org_id == org.id))
        ).scalars().all()
        subs = (
            await db.execute(select(TripSubscription).where(TripSubscription.org_id == org.id))
        ).scalars().all()

        bot = settings.telegram_bot_username.strip().lstrip("@") or "(nomi sozlanmagan)"
        print(f"Tashkilot : {org.name}")
        print(f"Bot       : @{bot}  ·  token: {'bor' if settings.telegram_configured else 'YO`Q'}")

        live = [a for a in accounts if a.chat_id and a.is_active]
        print(f"\nAvtopark egasi chatlari: {len(live)}/{len(accounts)} faol")
        for account in accounts:
            mark = "✓" if account.chat_id and account.is_active else "·"
            state = "faol" if account.chat_id else "havola ochilmagan"
            print(f"  {mark} {account.label or account.id} — {state}")

        active_subs = [s for s in subs if s.chat_id]
        print(f"\nYuk egasi obunalari: {len(active_subs)}/{len(subs)} faol")
        trip_by_id = {
            t.id: t
            for t in (
                await db.execute(select(Trip).where(Trip.org_id == org.id))
            ).scalars().all()
        }
        for sub in subs:
            trip = trip_by_id.get(sub.trip_id)
            mark = "✓" if sub.chat_id else "·"
            ref = trip.reference if trip else "?"
            state = "faol" if sub.chat_id else "havola ochilmagan"
            print(f"  {mark} {ref} — {sub.contact_name} — {state}")

        if not live:
            print("\n!! Avtopark egasi hech qaysi chatni ochmagan — `owner` buyruqlari jim qoladi.")
        if not active_subs:
            print("!! Hech bir yuk egasi havolani ochmagan — `customer` buyruqlari jim qoladi.")


# --------------------------------------------------------------------------- #
# Owner alerts                                                                 #
# --------------------------------------------------------------------------- #

async def cmd_owner_watcher(name: str) -> None:
    require_telegram()
    module, kinds, label = WATCHERS[name]
    async with SessionLocal() as db:
        org = await demo_org(db)
        cleared = await clear_dedupe(db, org, kinds)
        print(f"{label}: {cleared} ta eski yozuv tozalandi, tekshiruv ishga tushdi...")
        sent = await module.run(db)  # type: ignore[attr-defined]
    print(f"  → {sent} ta xabar yuborildi")


async def cmd_owner_reports() -> None:
    """Close last month's books now, instead of waiting for the 1st.

    ``reports.run`` fires only on the closing day, and takes ``today`` for
    exactly this reason. Handing it the first of *this* month resolves the
    period to the last complete one — August on a day in September — which is
    the month the workbooks should cover. Asking for the current month would
    hand the owner a half-finished ledger.
    """
    require_telegram()
    async with SessionLocal() as db:
        org = await demo_org(db)
        cleared = await clear_dedupe(db, org, ("report_ready",))
        first_of_month = datetime.now(report_tz()).date().replace(day=1)
        period = resolve_period("month", 1, today=first_of_month)
        print(f"oylik yopilish ({period.label}): {cleared} ta eski yozuv tozalandi...")
        sent = await owner_reports.run(db, today=first_of_month)
    print(f"  → {sent} ta hujjat yuborildi")


async def cmd_owner_briefing() -> None:
    """The morning digest, without waiting for morning.

    ``briefing.run`` gates on the local hour, which is the right behaviour for
    a scheduler and the wrong one for a presentation, so the pipeline is
    re-assembled here: same facts, same composer, same bus — only the clock is
    skipped. Yesterday is the day it summarises, exactly as the real job does.
    """
    require_telegram()
    async with SessionLocal() as db:
        org = await demo_org(db)
        await clear_dedupe(db, org, ("briefing",))

        day = datetime.now(report_tz()).date() - timedelta(days=1)
        facts = await owner_briefing.collect(db, org.id, day)
        lines = await owner_briefing.compose_with_ai(facts) or owner_briefing.render_plain(facts)
        sent = await notify_owner(db, org.id, owner_briefing.build_alert(facts, lines))
    print(f"ertalabki xulosa ({day.strftime('%d.%m.%Y')}) → {sent} ta xabar yuborildi")


# --------------------------------------------------------------------------- #
# Cargo-owner notifications                                                    #
# --------------------------------------------------------------------------- #

async def cmd_customer_daily() -> None:
    """The cargo owners' morning update, for this org's subscriptions only.

    Deliberately not ``daily_updates._run_batch``: that query is global, and on
    production it would push an unscheduled message to every real customer's
    cargo owners the moment a presenter pressed a key here.
    """
    require_telegram()
    async with SessionLocal() as db:
        org = await demo_org(db)
        subs = (
            await db.execute(
                select(TripSubscription).where(
                    TripSubscription.org_id == org.id,
                    TripSubscription.chat_id.is_not(None),
                    TripSubscription.daily_enabled.is_(True),
                )
            )
        ).scalars().all()
        if not subs:
            print("hech bir yuk egasi havolani ochmagan — yuboriladigan xabar yo'q")
            return

        sent = 0
        for sub in subs:
            trip = (
                await db.execute(select(Trip).where(Trip.id == sub.trip_id))
            ).scalar_one_or_none()
            if trip is None or trip.status == TripStatus.delivered:
                continue

            location = None
            if trip.truck_id:
                location = (
                    await db.execute(
                        select(TruckLocation).where(TruckLocation.truck_id == trip.truck_id)
                    )
                ).scalar_one_or_none()

            text = format_daily_update(
                trip.reference,
                trip.status,
                float(location.latitude) if location else None,
                float(location.longitude) if location else None,
                trip.destination_name,
                float(location.speed) if location and location.speed is not None else None,
                location.recorded_at if location else None,
            )
            result = await send_message(sub.chat_id, text)
            if result.ok:
                sub.last_daily_at = datetime.now(timezone.utc)
                sent += 1
            else:
                print(f"  ! {trip.reference}: yuborilmadi (HTTP {result.status_code})")
        await db.commit()
    print(f"ertalabki xabar → {sent}/{len(subs)} ta yuk egasiga yuborildi")


async def cmd_customer_status(reference: str, status: str | None, note: str | None) -> None:
    """Push one trip's status to its subscribers, without moving the trip.

    Separate from the dispatcher's real ``/advance`` click on purpose: the
    click is the story worth telling on stage and it already sends this
    message. This exists for the rehearsal, and for the second and third time
    the same beat has to be shown — a trip can only be advanced once.
    """
    require_telegram()
    async with SessionLocal() as db:
        org = await demo_org(db)
        trip = (
            await db.execute(
                select(Trip).where(Trip.org_id == org.id, Trip.reference == reference)
            )
        ).scalar_one_or_none()
        if trip is None:
            raise SystemExit(f"reys {reference!r} topilmadi")

        subs = (
            await db.execute(
                select(TripSubscription).where(
                    TripSubscription.trip_id == trip.id,
                    TripSubscription.chat_id.is_not(None),
                    TripSubscription.event_enabled.is_(True),
                )
            )
        ).scalars().all()
        if not subs:
            print(f"{reference}: yuk egasi havolani ochmagan — yuboriladigan xabar yo'q")
            return

        to_status = TripStatus(status) if status else trip.status

        location = None
        if trip.truck_id:
            location = (
                await db.execute(
                    select(TruckLocation).where(TruckLocation.truck_id == trip.truck_id)
                )
            ).scalar_one_or_none()

        text = format_status_change(
            trip.reference,
            to_status,
            float(location.latitude) if location else None,
            float(location.longitude) if location else None,
            note,
        )
        sent = 0
        for sub in subs:
            result = await send_message(sub.chat_id, text)
            if result.ok:
                sent += 1
            else:
                print(f"  ! {sub.contact_name}: yuborilmadi (HTTP {result.status_code})")
    print(f"{reference} → {to_status.value}: {sent}/{len(subs)} ta yuk egasiga yuborildi")


# --------------------------------------------------------------------------- #

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fire the demo tenant's Telegram messages.")
    sub = parser.add_subparsers(dest="group", required=True)

    sub.add_parser("status", help="Nima ulangani — yig'ilishdan oldin tekshiring")

    owner = sub.add_parser("owner", help="Avtopark egasiga xabar")
    owner.add_argument("what", choices=["briefing", *WATCHERS, "reports", "all"])

    customer = sub.add_parser("customer", help="Yuk egasiga xabar")
    customer_sub = customer.add_subparsers(dest="what", required=True)
    customer_sub.add_parser("daily", help="Ertalabki xabar")
    status_cmd = customer_sub.add_parser("status", help="Reys holati o'zgardi")
    status_cmd.add_argument("reference", help="Masalan: TR-2026-0021")
    status_cmd.add_argument("--status", default=None,
                            choices=[s.value for s in TripStatus],
                            help="Yuboriladigan holat (standart: reysning joriy holati)")
    status_cmd.add_argument("--note", default=None, help="Xabarga qo'shiladigan izoh")
    return parser


async def dispatch(args: argparse.Namespace) -> None:
    if args.group == "status":
        await cmd_status()
    elif args.group == "owner":
        if args.what == "briefing":
            await cmd_owner_briefing()
        elif args.what == "reports":
            await cmd_owner_reports()
        elif args.what == "all":
            await cmd_owner_briefing()
            for name in WATCHERS:
                await cmd_owner_watcher(name)
            await cmd_owner_reports()
        else:
            await cmd_owner_watcher(args.what)
    elif args.group == "customer":
        if args.what == "daily":
            await cmd_customer_daily()
        else:
            await cmd_customer_status(args.reference, args.status, args.note)


if __name__ == "__main__":
    asyncio.run(dispatch(build_parser().parse_args()))
