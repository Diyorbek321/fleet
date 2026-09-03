"""Reys nazoratchisi: which trips reach an owner's phone, and how they read.

Two failure modes are worth more than the rest. The first is a message the
owner cannot act on in two seconds — a reference number where the plate should
be. The second is the same true fact arriving every fifteen minutes until the
bot is muted, after which none of the other watchers matter either.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.core.config import settings
from app.models.drivers import Driver
from app.models.enums import TripEventType, TripStatus
from app.models.organizations import Organization
from app.models.owner_alerts import AlertSeverity, TelegramAccount
from app.models.trips import Trip, TripEvent
from app.models.trucks import Truck
from app.services.owner_alerts import bus
from app.services.owner_alerts.trips import (
    MAX_ALERTS_PER_ORG,
    _dative,
    _humanize_lateness,
    _place,
    _severity_for_lateness,
    run,
)
from app.services.telegram import SendResult


# ── Pure text and grading (no DB) ────────────────────────────────────────


@pytest.mark.parametrize(
    "late,expected",
    [
        (timedelta(minutes=90), "1 soat"),
        (timedelta(hours=6), "6 soat"),
        (timedelta(hours=6, minutes=59), "6 soat"),
        (timedelta(hours=26), "1 kun 2 soat"),
        (timedelta(days=2), "2 kun"),
    ],
)
def test_lateness_reads_in_the_largest_honest_unit(late: timedelta, expected: str):
    """"38 soat" makes an owner do arithmetic; "1 kun 14 soat" does not.

    Floored, never rounded up: a message claiming seven hours when it is six
    and a half starts an argument with the driver about a number that did not
    need to be precise.
    """
    assert _humanize_lateness(late) == expected


@pytest.mark.parametrize(
    "place,expected",
    [
        ("Moskva", "Moskvaga"),
        ("Toshkent", "Toshkentga"),
        ("Bishkek", "Bishkekka"),
        ("Chirchiq", "Chirchiqqa"),
    ],
)
def test_the_destination_takes_the_dative_its_ending_calls_for(place: str, expected: str):
    """A flat "+ga" writes "Bishkekga", which reads as foreign to the person
    paying for the product."""
    assert _dative(place) == expected


def test_a_full_address_is_trimmed_back_to_the_city():
    """Dispatchers type whatever the customer sent them; a title is one line."""
    assert _place("Moskva, Rossiya, ul. Lenina 5") == "Moskva"


def test_no_amount_of_lateness_is_critical():
    """``critical`` is the one severity that ignores quiet hours.

    A truck that has been late since yesterday afternoon is not fixable at
    03:00, so waking the owner buys nothing and costs the bot its welcome.
    """
    assert _severity_for_lateness(timedelta(days=9)) is AlertSeverity.warning


def test_a_truck_barely_behind_schedule_is_only_worth_an_info_line():
    """Default chats start at ``warning``, so this is the level that says
    "visible to owners who asked for the play-by-play, invisible otherwise"."""
    assert _severity_for_lateness(timedelta(hours=2)) is AlertSeverity.info


# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture
def captured_sends(monkeypatch) -> list[tuple[str, str]]:
    """Replace the Telegram transport and switch the feature gate on."""
    monkeypatch.setattr(settings, "telegram_bot_token", "TEST:token", raising=False)
    sends: list[tuple[str, str]] = []

    async def _fake_send(chat_id, text, *, disable_notification=False):
        sends.append((chat_id, text))
        return SendResult(ok=True, status_code=200)

    monkeypatch.setattr(bus, "send_message", _fake_send)
    return sends


async def _fleet(
    db, *, name: str = "Alert Co", plate: str | None = "01A123BC", driver: str | None = "Anvar"
) -> tuple[Organization, Truck | None, Driver | None]:
    org = Organization(name=name)
    db.add(org)
    await db.flush()

    truck = Truck(org_id=org.id, name=plate, plate_number=plate) if plate else None
    driver_row = (
        Driver(org_id=org.id, name=driver, license_number=f"LIC-{uuid.uuid4().hex[:8]}")
        if driver
        else None
    )
    for row in (truck, driver_row):
        if row is not None:
            db.add(row)
    await db.commit()
    return org, truck, driver_row


async def _link_chat(
    db, org_id, *, chat_id: str = "900001", min_severity: AlertSeverity = AlertSeverity.info
) -> TelegramAccount:
    account = TelegramAccount(
        org_id=org_id,
        token=uuid.uuid4().hex,
        chat_id=chat_id,
        min_severity=min_severity,
        muted_kinds=[],
        # Explicit: the model defaults to a 22→07 quiet window, and a suite
        # that passes by day and fails at night is worse than no suite.
        quiet_from_hour=None,
        quiet_to_hour=None,
    )
    db.add(account)
    await db.commit()
    return account


async def _trip(
    db,
    org: Organization,
    truck: Truck | None,
    driver: Driver | None,
    *,
    reference: str = "TR-2026-000042",
    status: TripStatus = TripStatus.en_route,
    late_by: timedelta | None = None,
    origin: str | None = "Toshkent",
    destination: str | None = "Moskva",
) -> Trip:
    trip = Trip(
        org_id=org.id,
        reference=reference,
        truck_id=truck.id if truck else None,
        driver_id=driver.id if driver else None,
        status=status,
        origin_name=origin,
        destination_name=destination,
        scheduled_end=(datetime.now(timezone.utc) - late_by) if late_by else None,
    )
    db.add(trip)
    await db.commit()
    return trip


async def _event(
    db,
    trip: Trip,
    to_status: TripStatus,
    *,
    from_status: TripStatus | None = TripStatus.en_route,
    ago: timedelta = timedelta(minutes=5),
    note: str | None = None,
) -> TripEvent:
    event = TripEvent(
        trip_id=trip.id,
        event=TripEventType.status_change,
        from_status=from_status,
        to_status=to_status,
        note=note,
        recorded_at=datetime.now(timezone.utc) - ago,
    )
    db.add(event)
    await db.commit()
    return event


# ── Lateness ─────────────────────────────────────────────────────────────


async def test_a_late_trip_leads_with_the_plate_then_the_driver(db, captured_sends):
    """The whole message is one glance long, and the glance has to land.

    An owner knows the fleet as "Anvar's truck"; TR-2026-000042 means nothing
    until they open the panel, so it comes third — after the two things that
    let them place the load without looking anything up.
    """
    org, truck, driver = await _fleet(db)
    await _link_chat(db, org.id)
    await _trip(db, org, truck, driver, late_by=timedelta(hours=6))

    assert await run(db) == 1
    text = captured_sends[0][1]
    assert "01A123BC - Anvar - TR-2026-000042 Moskvaga 6 soat kechikdi" in text
    assert "Holati: <b>yo'lda</b>" in text
    assert "Yo'nalish: <b>Toshkent → Moskva</b>" in text
    assert "Reja: <b>" in text


@pytest.mark.parametrize("status", [TripStatus.delivered, TripStatus.cancelled])
async def test_a_settled_trip_is_never_late(db, captured_sends, status: TripStatus):
    """Delivery and cancellation both end the clock. Without this, every
    completed trip whose paperwork ran past its slot nags forever."""
    org, truck, driver = await _fleet(db)
    await _link_chat(db, org.id)
    await _trip(db, org, truck, driver, status=status, late_by=timedelta(days=3))

    assert await run(db) == 0
    assert captured_sends == []


async def test_a_trip_inside_the_hour_of_grace_is_left_alone(db, captured_sends):
    """Border queues and Tashkent traffic cost an hour routinely. A fleet where
    every trip pings at minute one is a fleet where nobody reads the pings."""
    org, truck, driver = await _fleet(db)
    await _link_chat(db, org.id)
    await _trip(db, org, truck, driver, late_by=timedelta(minutes=30))

    assert await run(db) == 0


async def test_a_trip_forgotten_for_months_stops_nagging(db, captured_sends):
    """A trip abandoned in "planned" last spring is a data-entry problem, not
    an operational one, and repeating it daily is how the bot gets muted."""
    org, truck, driver = await _fleet(db)
    await _link_chat(db, org.id)
    await _trip(
        db, org, truck, driver, status=TripStatus.planned, late_by=timedelta(days=90)
    )

    assert await run(db) == 0


async def test_a_late_trip_is_announced_once_per_step_of_severity(db, captured_sends):
    """The tick is every fifteen minutes and the fact does not change.

    It only changes when the trip stops being slightly behind and starts being
    a problem — which is exactly when the owner should hear a second time.
    """
    org, truck, driver = await _fleet(db)
    await _link_chat(db, org.id)
    trip = await _trip(db, org, truck, driver, late_by=timedelta(hours=2))

    assert await run(db) == 1
    assert await run(db) == 0

    trip.scheduled_end = datetime.now(timezone.utc) - timedelta(hours=5)
    await db.commit()

    assert await run(db) == 1
    assert await run(db) == 0
    assert len(captured_sends) == 2


async def test_a_trip_with_no_truck_or_driver_still_reaches_the_owner(db, captured_sends):
    """An inner join would hide exactly the trips most worth chasing: a load
    past its delivery slot that nobody has been assigned to."""
    org, _, _ = await _fleet(db, plate=None, driver=None)
    await _link_chat(db, org.id)
    await _trip(db, org, None, None, late_by=timedelta(hours=6))

    assert await run(db) == 1
    assert "mashinasiz - haydovchisiz - TR-2026-000042" in captured_sends[0][1]


# ── Status changes ───────────────────────────────────────────────────────


async def test_a_status_change_is_read_back_out_of_the_timeline(db, captured_sends):
    """The dispatcher panel and the driver app both advance trips; the
    trip_events row is the only thing common to both paths."""
    org, truck, driver = await _fleet(db)
    await _link_chat(db, org.id)
    trip = await _trip(db, org, truck, driver, status=TripStatus.delivered)
    await _event(db, trip, TripStatus.delivered, note="CMR imzolandi")

    assert await run(db) == 1
    text = captured_sends[0][1]
    assert "01A123BC - Anvar - TR-2026-000042 yetkazildi" in text
    assert "Izoh: CMR imzolandi" in text


async def test_a_status_change_is_announced_once_however_often_the_tick_runs(
    db, captured_sends
):
    """Ninety-six copies of "yetkazildi" is the same thing as a muted bot."""
    org, truck, driver = await _fleet(db)
    await _link_chat(db, org.id)
    trip = await _trip(db, org, truck, driver, status=TripStatus.delivered)
    await _event(db, trip, TripStatus.delivered)

    assert await run(db) == 1
    assert await run(db) == 0
    assert len(captured_sends) == 1


async def test_re_saving_the_status_a_trip_already_had_is_not_progress(db, captured_sends):
    """The advance endpoint writes a timeline row whether or not the status
    moved, so a dispatcher double-clicking must not read as news."""
    org, truck, driver = await _fleet(db)
    await _link_chat(db, org.id)
    trip = await _trip(db, org, truck, driver, status=TripStatus.at_border)
    await _event(db, trip, TripStatus.at_border, from_status=TripStatus.at_border)

    assert await run(db) == 0


async def test_the_same_status_reached_twice_is_still_one_piece_of_news(db, captured_sends):
    """A trip sent back to the border produces a second row and no new fact,
    which is why the dedupe key names the trip and the status, not the row."""
    org, truck, driver = await _fleet(db)
    await _link_chat(db, org.id)
    trip = await _trip(db, org, truck, driver, status=TripStatus.at_border)
    await _event(
        db, trip, TripStatus.at_border, from_status=TripStatus.en_route, ago=timedelta(hours=4)
    )
    await _event(
        db, trip, TripStatus.at_border, from_status=TripStatus.en_route, ago=timedelta(minutes=5)
    )

    assert await run(db) == 1


async def test_a_status_change_older_than_the_window_is_not_replayed(db, captured_sends):
    """Otherwise the first tick after a deploy narrates last week to everyone."""
    org, truck, driver = await _fleet(db)
    await _link_chat(db, org.id)
    trip = await _trip(db, org, truck, driver, status=TripStatus.delivered)
    await _event(db, trip, TripStatus.delivered, ago=timedelta(hours=36))

    assert await run(db) == 0


async def test_routine_progress_stays_quiet_for_a_chat_on_its_defaults(db, captured_sends):
    """A new chat's minimum is ``warning``, and that has to mean something.

    Deliveries are good news the owner can read in the panel; a cancellation is
    revenue that just disappeared. Grading them the same would either drown the
    second one or hide it.
    """
    org, truck, driver = await _fleet(db)
    await _link_chat(db, org.id, min_severity=AlertSeverity.warning)

    delivered = await _trip(db, org, truck, driver, status=TripStatus.delivered)
    await _event(db, delivered, TripStatus.delivered)
    assert await run(db) == 0

    cancelled = await _trip(
        db, org, truck, driver, reference="TR-2026-000043", status=TripStatus.cancelled
    )
    await _event(db, cancelled, TripStatus.cancelled)

    assert await run(db) == 1
    assert "TR-2026-000043 bekor qilindi" in captured_sends[0][1]


# ── Boundaries ───────────────────────────────────────────────────────────


async def test_neither_signal_crosses_an_organization(db, captured_sends):
    """Both queries sweep the whole platform in one pass, so the org each row
    is notified under is the only thing keeping one customer's trips off
    another customer's phone."""
    org_a, truck_a, driver_a = await _fleet(db, name="A Co", plate="01A111AA", driver="Anvar")
    org_b, truck_b, driver_b = await _fleet(db, name="B Co", plate="01B222BB", driver="Bekzod")
    await _link_chat(db, org_a.id)

    trip_b = await _trip(
        db, org_b, truck_b, driver_b, reference="TR-B-1", late_by=timedelta(hours=6)
    )
    await _event(db, trip_b, TripStatus.delivered)
    assert await run(db) == 0
    assert captured_sends == []

    await _trip(db, org_a, truck_a, driver_a, reference="TR-A-1", late_by=timedelta(hours=6))
    assert await run(db) == 1
    assert "01A111AA" in captured_sends[0][1]


async def test_a_transport_that_explodes_neither_crashes_the_tick_nor_eats_the_fact(
    db, monkeypatch
):
    """The scheduler gives each signal one chance every fifteen minutes. A
    Telegram outage must cost one tick, not the alert."""
    monkeypatch.setattr(settings, "telegram_bot_token", "TEST:token", raising=False)

    async def _explode(chat_id, text, *, disable_notification=False):
        raise RuntimeError("telegram exploded")

    monkeypatch.setattr(bus, "send_message", _explode)

    org, truck, driver = await _fleet(db)
    await _link_chat(db, org.id)
    await _trip(db, org, truck, driver, late_by=timedelta(hours=6))

    assert await run(db) == 0

    sends: list[tuple[str, str]] = []

    async def _recovered(chat_id, text, *, disable_notification=False):
        sends.append((chat_id, text))
        return SendResult(ok=True, status_code=200)

    monkeypatch.setattr(bus, "send_message", _recovered)
    assert await run(db) == 1
    assert len(sends) == 1


# ── Volume control ───────────────────────────────────────────────────────
#
# One border closing makes every truck late at once. Without a ceiling that is
# one Telegram message per truck in a single tick, and an owner who mutes the
# bot in week one takes every other watcher down with it.


async def test_a_fleet_wide_delay_arrives_capped_with_the_rest_rolled_up(db, captured_sends):
    """Twenty late trucks must not be twenty pings.

    The cap is the whole point: what an owner needs at 09:00 is "your fleet is
    stuck", not a message per registration plate.
    """
    org, truck, driver = await _fleet(db)
    await _link_chat(db, org.id)
    for n in range(9):
        await _trip(
            db, org, truck, driver,
            reference=f"TR-2026-0000{n:02d}",
            late_by=timedelta(hours=5 + n),
        )

    await run(db)

    assert len(captured_sends) == MAX_ALERTS_PER_ORG + 1
    roll_up = captured_sends[-1][1]
    assert "Yana 4 ta" in roll_up


async def test_the_longest_late_truck_is_the_one_that_gets_through(db, captured_sends):
    """A cap only helps if it keeps the right ones.

    Ordered worst-first, so the truck that has been late longest is in the
    message an owner actually reads.
    """
    org, truck, driver = await _fleet(db)
    await _link_chat(db, org.id)
    await _trip(db, org, truck, driver, reference="TR-WORST", late_by=timedelta(days=3))
    for n in range(MAX_ALERTS_PER_ORG + 2):
        await _trip(
            db, org, truck, driver,
            reference=f"TR-MILD-{n}",
            late_by=timedelta(hours=2),
        )

    await run(db)

    assert any("TR-WORST" in text for _chat, text in captured_sends)


async def test_the_capped_remainder_is_not_recorded_so_it_drains(db, captured_sends):
    """Held-back trips must arrive on the next tick, not vanish.

    The bus suppresses a fact it has already recorded, so a cap that recorded
    what it skipped would silently drop those trucks for the whole TTL.
    """
    org, truck, driver = await _fleet(db)
    await _link_chat(db, org.id)
    for n in range(MAX_ALERTS_PER_ORG + 3):
        await _trip(
            db, org, truck, driver,
            reference=f"TR-2026-0001{n:02d}",
            late_by=timedelta(hours=5 + n),
        )

    await run(db)
    first_pass = {text for _chat, text in captured_sends}
    captured_sends.clear()

    await run(db)
    second_pass = {text for _chat, text in captured_sends}

    # The three held back last time come through now, and none of the five
    # already delivered repeats.
    assert second_pass
    assert not (second_pass & first_pass)


async def test_one_busy_fleet_does_not_crowd_out_another(db, captured_sends):
    """The cap is per organization, so a noisy customer cannot starve a quiet one."""
    busy, busy_truck, busy_driver = await _fleet(db, name="Busy Co", plate="01A111AA")
    quiet, quiet_truck, quiet_driver = await _fleet(db, name="Quiet Co", plate="01B222BB")
    await _link_chat(db, busy.id, chat_id="900101")
    await _link_chat(db, quiet.id, chat_id="900102")

    for n in range(MAX_ALERTS_PER_ORG + 4):
        await _trip(db, busy, busy_truck, busy_driver, reference=f"TR-B-{n}", late_by=timedelta(hours=6))
    await _trip(db, quiet, quiet_truck, quiet_driver, reference="TR-Q-1", late_by=timedelta(hours=6))

    await run(db)

    assert any("TR-Q-1" in text for chat, text in captured_sends if chat == "900102")
