"""Print every Telegram message the demo tenant would send, without sending one.

``demo_fire.py`` is the remote for the live walkthrough; this is the rehearsal.
It answers the question a presenter has the night before — *what exactly lands
on the customer's phone?* — and it answers it from the real data, through the
real formatters, with no chat activated and nothing delivered.

    python demo_preview.py                 # everything
    python demo_preview.py --owner         # only the fleet owner's alerts
    python demo_preview.py --customer      # only the cargo owner's messages
    python demo_preview.py --json          # machine-readable, for a rendered page

**Nothing is written and nothing is sent.** Two substitutions make that true,
both in this process only:

* ``notify_owner`` is replaced in each watcher module with a collector. That
  function is also the one that writes ``notification_log``, so bypassing it
  means the dedupe rows the real alerts depend on are left untouched — a
  preview run cannot silence the alerts the demo is about to show.
* the "which organizations have a live chat" selectors are replaced with the
  demo org. The watchers otherwise skip every org whose owner has not opened a
  deep link yet, which before a demo is all of them.

The alternative — stamping a chat id on the demo org so the watchers proceed —
would have been read by the scheduler running in the same container, which
would then try to deliver to a chat that does not exist, mark the account dead
after the failure, and write the dedupe rows this exists to protect.
"""
from __future__ import annotations

import argparse
import asyncio
import html
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import select

import demo_data_uz as D
from app.core.config import settings
from app.core.database import SessionLocal
from app.models.enums import TripStatus
from app.models.notifications import TripSubscription
from app.models.organizations import Organization
from app.models.trips import Trip
from app.models.trucks import TruckLocation
from app.services.owner_alerts import briefing as owner_briefing
from app.services.owner_alerts import cash as owner_cash
from app.services.owner_alerts import expiry as owner_expiry
from app.services.owner_alerts import leakage as owner_leakage
from app.services.owner_alerts import trips as owner_trips
from app.services.owner_alerts.bus import render_alert
from app.services.period_reports import report_tz
from app.services.telegram import format_daily_update, format_status_change

# (module, human label, the org-selector attribute to neutralise)
WATCHERS = [
    (owner_briefing, "Ertalabki xulosa", "_listening_org_ids"),
    (owner_leakage, "Yo'qotishlar", "_orgs_with_owner_chats"),
    (owner_trips, "Reys holati va kechikishlar", None),
    (owner_expiry, "Hujjat va texnik ko'rik muddatlari", "_org_ids_with_a_listening_chat"),
    (owner_cash, "Kassa nomuvofiqligi", None),
]


def to_plain(text: str) -> str:
    """Telegram HTML as a reader sees it in the chat.

    Bold and italic tags carry no information once the message is being read on
    paper, and a link is more useful as its own label than as a URL nobody will
    type.
    """
    def _link(m: re.Match) -> str:
        href, label = m.group(1), m.group(2)
        coords = re.search(r"[?&]q=([-\d.]+,[-\d.]+)", href)
        return f"{label} → {coords.group(1)}" if coords else label

    text = re.sub(r'<a [^>]*href="([^"]*)"[^>]*>(.*?)</a>', _link, text, flags=re.S)
    text = re.sub(r"</?(b|i|u|s|code|pre)>", "", text)
    return html.unescape(text).strip()


async def demo_org(db) -> Organization:
    org = (
        await db.execute(select(Organization).where(Organization.name == D.ORG_NAME))
    ).scalar_one_or_none()
    if org is None:
        raise SystemExit(f"organization {D.ORG_NAME!r} not found — run seed_demo_uz.py first")
    return org


# --------------------------------------------------------------------------- #
# Fleet owner                                                                  #
# --------------------------------------------------------------------------- #

async def owner_messages(db, org) -> list[dict]:
    """Run each watcher with delivery swapped out, and keep what it wanted to say."""
    out: list[dict] = []

    # Two watchers return 0 immediately when no bot token is configured, which
    # on a laptop is always — and the rehearsal a presenter most wants to read
    # is the one they run before leaving the house. The flag is flipped in this
    # process only, and it cannot cause a send: notify_owner, the sole path to
    # Telegram from here, is replaced below.
    original_token = settings.telegram_bot_token
    settings.telegram_bot_token = original_token or "preview-only"

    for module, label, selector in WATCHERS:
        captured: list = []

        async def collect(_db, _org_id, alert, _captured=captured) -> int:
            _captured.append(alert)
            return 1  # the watchers count this as "delivered" and carry on

        original_notify = module.notify_owner
        original_selector = getattr(module, selector) if selector else None
        module.notify_owner = collect
        if selector:
            async def only_demo_org(_db, _org_id=org.id):
                return [_org_id]
            setattr(module, selector, only_demo_org)

        try:
            if module is owner_briefing:
                # run() gates on the local hour; the digest itself does not.
                day = datetime.now(report_tz()).date() - timedelta(days=1)
                facts = await module.collect(db, org.id, day)
                lines = module.render_plain(facts)
                captured.append(module.build_alert(facts, lines))
            else:
                await module.run(db)
        except Exception as exc:  # noqa: BLE001 — a preview must not die on one watcher
            print(f"  !! {label}: {type(exc).__name__}: {exc}", file=sys.stderr)
        finally:
            module.notify_owner = original_notify
            if selector:
                setattr(module, selector, original_selector)

        for alert in captured:
            out.append({
                "group": label,
                "kind": alert.kind.value,
                "severity": alert.severity.value,
                "text": to_plain(render_alert(alert)),
            })

    settings.telegram_bot_token = original_token
    return out


# --------------------------------------------------------------------------- #
# Cargo owner                                                                  #
# --------------------------------------------------------------------------- #

LIVE = (TripStatus.planned, TripStatus.loading, TripStatus.en_route, TripStatus.at_border)


async def customer_messages(db, org) -> list[dict]:
    """Both message types, for every trip a cargo owner is subscribed to."""
    subs = (
        await db.execute(select(TripSubscription).where(TripSubscription.org_id == org.id))
    ).scalars().all()
    trips = {
        t.id: t
        for t in (
            await db.execute(select(Trip).where(Trip.org_id == org.id, Trip.status.in_(LIVE)))
        ).scalars().all()
    }

    out: list[dict] = []
    for sub in subs:
        trip = trips.get(sub.trip_id)
        if trip is None:
            continue

        location = None
        if trip.truck_id:
            location = (
                await db.execute(
                    select(TruckLocation).where(TruckLocation.truck_id == trip.truck_id)
                )
            ).scalar_one_or_none()
        lat = float(location.latitude) if location else None
        lng = float(location.longitude) if location else None
        speed = float(location.speed) if location and location.speed is not None else None

        out.append({
            "group": "Holat o'zgardi (dispetcher tugmani bosganda)",
            "trip": trip.reference,
            "contact": sub.contact_name,
            "text": to_plain(format_status_change(trip.reference, trip.status, lat, lng, None)),
        })
        out.append({
            "group": "Ertalabki xabar (har kuni avtomatik)",
            "trip": trip.reference,
            "contact": sub.contact_name,
            "text": to_plain(format_daily_update(
                trip.reference, trip.status, lat, lng, trip.destination_name,
                speed, location.recorded_at if location else None,
            )),
        })
    return out


# --------------------------------------------------------------------------- #

def render_text(owner: list[dict], customer: list[dict]) -> None:
    if customer:
        print("=" * 72)
        print("YUK MIJOZIGA BORADIGAN XABARLAR")
        print("=" * 72)
        for group in dict.fromkeys(m["group"] for m in customer):
            print(f"\n### {group}\n")
            for m in (x for x in customer if x["group"] == group):
                print(f"  ── {m['trip']} → {m['contact']} " + "─" * 24)
                for line in m["text"].splitlines():
                    print(f"  │ {line}")
                print()

    if owner:
        print("=" * 72)
        print("AVTOPARK EGASIGA BORADIGAN XABARLAR")
        print("=" * 72)
        groups = [label for _mod, label, _sel in WATCHERS]
        for group in groups:
            rows = [x for x in owner if x["group"] == group]
            print(f"\n### {group}  ({len(rows)} ta)\n")
            if not rows:
                print("  (hozir yuboradigan yangisi yo'q — bu signal bo'yicha\n"
                      "   hammasi allaqachon xabar qilingan yoki topilmadi)\n")
                continue
            for m in rows:
                print(f"  ── {m['severity']} · {m['kind']} " + "─" * 24)
                for line in m["text"].splitlines():
                    print(f"  │ {line}")
                print()


async def main(want_owner: bool, want_customer: bool, as_json: bool,
               out_path: str | None = None) -> None:
    async with SessionLocal() as db:
        org = await demo_org(db)
        owner = await owner_messages(db, org) if want_owner else []
        customer = await customer_messages(db, org) if want_customer else []

    if as_json:
        payload = json.dumps({"owner": owner, "customer": customer},
                             ensure_ascii=False, indent=2)
        if out_path:
            # The app's structured logger owns stdout, so a caller piping this
            # into a parser gets log lines wrapped around the document. Writing
            # the file here keeps the two streams apart.
            Path(out_path).write_text(payload, encoding="utf-8")
            print(f"yozildi: {out_path} ({len(payload)} bayt)")
        else:
            print(payload)
    else:
        render_text(owner, customer)
        print(f"\nJami: mijozga {len(customer)} ta, egasiga {len(owner)} ta xabar.")
        print("Hech biri yuborilmadi — bu faqat ko'rib chiqish uchun.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Preview the demo tenant's Telegram messages.")
    parser.add_argument("--owner", action="store_true", help="Faqat avtopark egasi xabarlari")
    parser.add_argument("--customer", action="store_true", help="Faqat yuk mijozi xabarlari")
    parser.add_argument("--json", action="store_true", help="JSON chiqarish")
    parser.add_argument("--out", default=None,
                        help="JSON'ni faylga yozish. stdout'ga structlog ham yozadi, "
                             "shuning uchun quvurga ulanganda shu bayroq kerak.")
    args = parser.parse_args()

    both = not (args.owner or args.customer)
    asyncio.run(main(args.owner or both, args.customer or both,
                     args.json or bool(args.out), args.out))
