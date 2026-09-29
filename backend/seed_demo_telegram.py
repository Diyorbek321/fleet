"""Give the Uzbek demo tenant its two Telegram audiences, for the live walkthrough.

``seed_demo_uz.py`` builds the fleet and ``seed_demo_driver.py`` issues the
mobile login. Neither creates a Telegram binding, because in real life both
bindings are minted by a human: a dispatcher presses "link" on a trip, an admin
presses "link" in settings. For a presentation that is one click too many per
persona, and the links have to exist *before* the room is watching.

This mints them up front:

* one ``TripSubscription`` per in-flight trip — the **cargo owner** (yuk egasi)
  who wants to know where their load is and has no account in the system;
* one ``TelegramAccount`` per entry in ``OWNER_CHATS`` — the **fleet owner**
  (avtopark egasi) who wants to know what the fleet cost today.

Both are magic-link flows, so a seeded row is only half the binding: the token
is live but ``chat_id`` is NULL until somebody opens the link in Telegram. The
script prints every link it minted so the presenter can open them beforehand
(or hand one to the prospect mid-demo, which is the better story).

**Scope**: every write is confined to the demo organization. Other tenants —
including real customers on production — are never read or touched, and
``--reset`` only deletes rows belonging to the demo org.

Run (after seed_demo_uz.py):

    python seed_demo_telegram.py                 # mint what is missing
    python seed_demo_telegram.py --reset         # drop this org's bindings first
    python seed_demo_telegram.py --owner-chat-id 123456789
                                                 # skip the link, bind a known chat

The owner-chat-id escape hatch exists because a demo cannot afford to discover
that a deep link did not open. Get the id once by messaging the bot and reading
``https://api.telegram.org/bot<TOKEN>/getUpdates``.
"""
from __future__ import annotations

import argparse
import asyncio
import secrets
import sys
from datetime import datetime, timezone
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
from app.models.owner_alerts import AlertSeverity, TelegramAccount
from app.models.trips import Trip
from app.services.owner_alerts.commands import build_owner_deep_link
from app.services.telegram import build_deep_link

# Statuses that mean "this load is moving and its owner is anxious about it".
# ``delivered`` is excluded on purpose: a subscription to a finished trip sends
# nothing, which on stage looks like a broken feature rather than a correct one.
LIVE = (TripStatus.planned, TripStatus.loading, TripStatus.en_route, TripStatus.at_border)


# --------------------------------------------------------------------------- #
# Reset                                                                        #
# --------------------------------------------------------------------------- #

async def reset_bindings(db, org: Organization) -> None:
    """Drop this org's Telegram bindings. Other tenants are never in scope."""
    subs = await db.execute(delete(TripSubscription).where(TripSubscription.org_id == org.id))
    accounts = await db.execute(delete(TelegramAccount).where(TelegramAccount.org_id == org.id))
    await db.commit()
    print(f"  reset: {subs.rowcount or 0} obuna, {accounts.rowcount or 0} egasi chati o'chirildi")


# --------------------------------------------------------------------------- #
# Cargo owners — one subscription per in-flight trip                           #
# --------------------------------------------------------------------------- #

async def seed_trip_subscriptions(db, org: Organization) -> list[tuple[Trip, TripSubscription]]:
    trips = (
        await db.execute(
            select(Trip)
            .where(Trip.org_id == org.id, Trip.status.in_(LIVE))
            .order_by(Trip.scheduled_start.desc())
        )
    ).scalars().all()
    if not trips:
        raise SystemExit("no in-flight trips in the demo org — run seed_demo_uz.py --reset first")

    existing = {
        sub.trip_id: sub
        for sub in (
            await db.execute(select(TripSubscription).where(TripSubscription.org_id == org.id))
        ).scalars().all()
    }

    pairs: list[tuple[Trip, TripSubscription]] = []
    minted = 0
    for i, trip in enumerate(trips):
        sub = existing.get(trip.id)
        if sub is None:
            name, phone, _company = D.CARGO_OWNERS[i % len(D.CARGO_OWNERS)]
            sub = TripSubscription(
                org_id=org.id,
                trip_id=trip.id,
                token=secrets.token_urlsafe(16),
                contact_name=name,
                contact_phone=phone,
                # New subscriptions start without the morning digest, but the
                # demo runbook shows it (demo_fire customer-daily).
                daily_enabled=True,
            )
            db.add(sub)
            minted += 1
        pairs.append((trip, sub))

    await db.commit()
    print(f"  yuk egalari: {len(pairs)} ta reysga obuna ({minted} ta yangi)")
    return pairs


# --------------------------------------------------------------------------- #
# Fleet owner — organization-level chats                                       #
# --------------------------------------------------------------------------- #

async def seed_owner_chats(db, org: Organization, chat_id: str | None) -> list[TelegramAccount]:
    """Mint the owner's chats with presentation-friendly delivery settings.

    Two deliberate departures from the product defaults, both because a demo is
    not a workday:

    * ``min_severity=info`` — the defaults drop everything below ``warning``,
      which is right for month three and wrong for the ten minutes where the
      point is to show that the bot talks at all;
    * no quiet window — ``quiet_from == quiet_to`` is read as "no window", so a
      demo that runs at 22:30 still delivers.
    """
    existing = {
        account.label: account
        for account in (
            await db.execute(select(TelegramAccount).where(TelegramAccount.org_id == org.id))
        ).scalars().all()
    }

    accounts: list[TelegramAccount] = []
    minted = 0
    for label, muted in D.OWNER_CHATS:
        account = existing.get(label)
        if account is None:
            account = TelegramAccount(
                org_id=org.id,
                token=secrets.token_urlsafe(16),
                label=label,
                muted_kinds=list(muted),
                min_severity=AlertSeverity.info,
                quiet_from_hour=0,
                quiet_to_hour=0,
                is_active=True,
            )
            db.add(account)
            minted += 1
        accounts.append(account)

    # Bind the known chat to the director's row only. Pointing both at one chat
    # would deliver every alert twice and make the accountant's mute list — the
    # thing worth showing — invisible.
    if chat_id and accounts:
        accounts[0].chat_id = chat_id
        accounts[0].activated_at = datetime.now(timezone.utc)

    await db.commit()
    print(f"  avtopark egasi: {len(accounts)} ta chat ({minted} ta yangi)")
    return accounts


# --------------------------------------------------------------------------- #
# Cheat sheet                                                                  #
# --------------------------------------------------------------------------- #

def print_cheat_sheet(
    pairs: list[tuple[Trip, TripSubscription]], accounts: list[TelegramAccount]
) -> None:
    bot = settings.telegram_bot_username.strip().lstrip("@")
    print("\n" + "=" * 72)
    print("TELEGRAM DEMO — havolalar")
    print("=" * 72)
    if not settings.telegram_configured:
        print("\n!! TELEGRAM_BOT_TOKEN sozlanmagan — havolalar ochilmaydi.")
        print("   Backend .env ga TELEGRAM_BOT_TOKEN va TELEGRAM_BOT_USERNAME qo'shing.")
    elif not bot:
        print("\n!! TELEGRAM_BOT_USERNAME bo'sh — havolalar tg:// ko'rinishida chiqadi.")

    print("\n--- 1. AVTOPARK EGASI (ushbu havolani o'zingiz oching) ---")
    for account in accounts:
        state = f"faol · chat {account.chat_id}" if account.chat_id else "kutilmoqda"
        muted = ", ".join(account.muted_kinds) if account.muted_kinds else "hech narsa o'chirilmagan"
        print(f"\n  {account.label}   [{state}]")
        print(f"    ovozsiz: {muted}")
        if not account.chat_id:
            print(f"    {build_owner_deep_link(account.token)}")

    print("\n--- 2. YUK MIJOZI (bittasini mijozning telefonida oching) ---")
    for trip, sub in pairs:
        state = "faol" if sub.chat_id else "kutilmoqda"
        route = f"{trip.origin_name} → {trip.destination_name}"
        print(f"\n  {trip.reference}  ·  {route}  ·  {trip.status.value}  [{state}]")
        print(f"    {sub.contact_name} ({sub.contact_phone})")
        if not sub.chat_id:
            print(f"    {build_deep_link(sub.token)}")
    print("\n" + "=" * 72)


# --------------------------------------------------------------------------- #

async def main(reset: bool, owner_chat_id: str | None) -> None:
    async with SessionLocal() as db:
        org = (
            await db.execute(select(Organization).where(Organization.name == D.ORG_NAME))
        ).scalar_one_or_none()
        if org is None:
            raise SystemExit(f"organization {D.ORG_NAME!r} not found — run seed_demo_uz.py first")

        print(f"Seeding Telegram personas for '{org.name}'...")
        if reset:
            await reset_bindings(db, org)

        pairs = await seed_trip_subscriptions(db, org)
        accounts = await seed_owner_chats(db, org, owner_chat_id)
        print_cheat_sheet(pairs, accounts)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed the demo tenant's Telegram personas.")
    parser.add_argument("--reset", action="store_true",
                        help="Delete this org's existing bindings first (other tenants untouched)")
    parser.add_argument("--owner-chat-id", default=None,
                        help="Bind a known Telegram chat id to the owner's first chat, "
                             "skipping the deep link")
    args = parser.parse_args()

    asyncio.run(main(reset=args.reset, owner_chat_id=args.owner_chat_id))
