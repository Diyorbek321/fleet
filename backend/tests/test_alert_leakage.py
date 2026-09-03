"""The leakage watcher: what counts as the same event twice, and how loud it gets.

Two things can break this feature, and neither of them looks like a wrong
message.

The first is identity. ``analytics`` recomputes over a rolling seven-day
window, so every finding comes back on every fifteen-minute tick for a week.
A key that drifts — because the window's trailing edge truncated a stop, or
because a list got re-sorted — turns one real event into a hundred messages.
The pure tests below pin the key to the underlying fact.

The second is volume. A bad week produces dozens of findings at once, and the
owner's only defence against a wall of text is muting the bot. So the cap is
tested from both sides: that it holds the tail back, and that it never eats it.

Rows are seeded through the ORM: GPS ingest always stamps "now", and every case
here needs backdated tracks.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models.maintenance import FuelLog
from app.models.organizations import Organization
from app.models.owner_alerts import AlertKind, AlertSeverity, NotificationLog, TelegramAccount
from app.models.trucks import Truck, TruckLocationHistory
from app.services.owner_alerts import bus, leakage
from app.services.telegram import SendResult

# Tashkent. Nothing here depends on the exact geography, only on "same place"
# vs "a couple of kilometres away".
BASE_LAT = 41.311
BASE_LNG = 69.241

# Midday in Tashkent (UTC+5), so adding minutes in a test never crosses a date.
MIDDAY_UTC = datetime(2026, 9, 2, 6, 0, tzinfo=timezone.utc)


# ── Synthetic analytics payloads (no DB) ─────────────────────────────────


def _stop_row(
    started_at: datetime,
    *,
    lat: float = BASE_LAT,
    lng: float = BASE_LNG,
    minutes: float = 45.0,
    truck_id: str = "truck-1",
    plate: str = "01A111AA",
) -> dict:
    return {
        "truck_id": truck_id,
        "truck_name": "Volvo",
        "plate_number": plate,
        "latitude": lat,
        "longitude": lng,
        "started_at": started_at,
        "ended_at": started_at + timedelta(minutes=minutes),
        "duration_minutes": minutes,
    }


def _fuel_row(*, flagged: bool = True, truck_id: str = "truck-1", waste: float = 900_000.0) -> dict:
    return {
        "truck_id": truck_id,
        "truck_name": "Volvo",
        "plate_number": "01A111AA",
        "distance_km": 1800.0,
        "liters": 900.0,
        "l_per_100km": 50.0,
        "baseline_l_per_100km": 32.0,
        "flagged": flagged,
        "estimated_waste_cost": waste,
    }


def _fraud_row(*, log_id: str, cost: float = 12_000_000.0, station: str | None = None) -> dict:
    return {
        "fuel_log_id": log_id,
        "truck_id": "truck-1",
        "truck_name": "Volvo",
        "plate_number": "01A111AA",
        "filled_at": MIDDAY_UTC,
        "liters": 1200.0,
        "cost_per_liter": 10_000.0,
        "total_cost": cost,
        "fuel_station": station,
        "reasons": ["oversized_fill"],
    }


def _stop_key(row: dict) -> str:
    return leakage._stop_findings({"stops": [row]})[0].dedupe_key


# ── Dedupe identity ──────────────────────────────────────────────────────


def test_a_stop_keeps_its_key_when_the_window_trims_its_first_minutes():
    """The load-bearing case for stops.

    Each tick re-scans a window whose trailing edge has moved, so a stop that
    straddles it loses its earliest points and reports a later ``started_at``.
    Keying on the exact timestamp would read that as a new stop and announce a
    week-old event a second time.
    """
    assert _stop_key(_stop_row(MIDDAY_UTC)) == _stop_key(
        _stop_row(MIDDAY_UTC + timedelta(minutes=12))
    )


def test_gps_jitter_at_the_same_parking_spot_is_one_stop():
    """A truck sitting still still reports coordinates that wobble by metres."""
    assert _stop_key(_stop_row(MIDDAY_UTC, lat=BASE_LAT, lng=BASE_LNG)) == _stop_key(
        _stop_row(MIDDAY_UTC, lat=BASE_LAT + 0.00004, lng=BASE_LNG - 0.00006)
    )


def test_the_same_spot_on_two_days_is_two_stops():
    """Parking at the same unauthorized yard every night is a nightly finding."""
    assert _stop_key(_stop_row(MIDDAY_UTC)) != _stop_key(
        _stop_row(MIDDAY_UTC + timedelta(days=1))
    )


def test_two_places_on_the_same_day_are_two_stops():
    """Otherwise the second half of a bad day is silently absorbed by the first."""
    assert _stop_key(_stop_row(MIDDAY_UTC)) != _stop_key(
        _stop_row(MIDDAY_UTC, lng=BASE_LNG + 0.03)  # ~2.5 km east
    )


def test_the_calendar_day_in_a_stop_key_is_the_owners_day_not_utc():
    """21:00 UTC is already tomorrow in Tashkent, and the owner reads it there."""
    late = datetime(2026, 9, 2, 20, 0, tzinfo=timezone.utc)
    assert ":2026-09-03:" in _stop_key(_stop_row(late))


def test_a_suspicious_fill_is_keyed_by_its_row_not_its_place_in_the_list():
    """``events`` is sorted by cost, so a cheaper fill appearing later shifts
    every position after it. Positional keys would re-announce the lot."""
    first, second = _fraud_row(log_id="log-a"), _fraud_row(log_id="log-b", cost=8_000_000.0)
    forward = {f.dedupe_key for f in leakage._fraud_findings({"events": [first, second]})}
    reversed_ = {f.dedupe_key for f in leakage._fraud_findings({"events": [second, first]})}
    assert forward == reversed_ == {"leakage:fraud:log-a", "leakage:fraud:log-b"}


def test_two_bad_fills_on_one_day_stay_two_things_to_check():
    """Keying a fill-up by truck+day would hide the second receipt."""
    findings = leakage._fraud_findings(
        {"events": [_fraud_row(log_id="log-a"), _fraud_row(log_id="log-b")]}
    )
    assert len({f.dedupe_key for f in findings}) == 2


def test_only_flagged_trucks_become_fuel_findings():
    """``fuel_anomalies`` returns every measurable truck, flagged or not."""
    report = {"window_days": 7, "trucks": [_fuel_row(flagged=False), _fuel_row(flagged=True)]}
    assert len(leakage._fuel_findings(report, "2026-09-02")) == 1


def test_a_fuel_flag_is_keyed_by_the_day_it_was_measured():
    """It is a state over the trailing week, not an event with a timestamp —
    so it is worth one line a day, not one line every fifteen minutes."""
    report = {"window_days": 7, "trucks": [_fuel_row()]}
    assert leakage._fuel_findings(report, "2026-09-02")[0].dedupe_key == (
        "leakage:fuel:truck-1:2026-09-02"
    )
    assert leakage._fuel_findings(report, "2026-09-03")[0].dedupe_key != (
        "leakage:fuel:truck-1:2026-09-02"
    )


def test_every_dedupe_key_fits_the_column():
    """``notification_log.dedupe_key`` is String(200); a truncated key silently
    collides with its neighbours and suppresses real findings."""
    keys = [
        _stop_key(_stop_row(MIDDAY_UTC, truck_id=str(uuid.uuid4()))),
        leakage._fuel_findings({"trucks": [_fuel_row(truck_id=str(uuid.uuid4()))]}, "2026-09-02")[
            0
        ].dedupe_key,
        leakage._fraud_findings({"events": [_fraud_row(log_id=str(uuid.uuid4()))]})[0].dedupe_key,
    ]
    assert max(len(key) for key in keys) <= 200


# ── Ranking and the roll-up ──────────────────────────────────────────────


def test_the_cap_keeps_receipts_over_hints_and_money_over_minutes():
    """Five lines is the whole budget, so it goes to the most actionable five:
    a fill-up an owner can physically go and check outranks a statistical
    efficiency flag, which outranks a long stop."""
    ranked = leakage.rank_findings(
        leakage._stop_findings({"stops": [_stop_row(MIDDAY_UTC)]})
        + leakage._fuel_findings({"trucks": [_fuel_row()]}, "2026-09-02")
        + leakage._fraud_findings({"events": [_fraud_row(log_id="log-a")]})
    )
    assert [f.category for f in ranked] == ["fraud", "fuel", "stop"]


def test_ranking_is_stable_across_ticks():
    """Two findings of equal weight must not swap places between runs, or the
    cap sends a different pair each tick and the backlog never drains."""
    rows = [
        _stop_row(MIDDAY_UTC, truck_id="truck-1", lng=BASE_LNG),
        _stop_row(MIDDAY_UTC, truck_id="truck-2", lng=BASE_LNG + 0.03),
    ]
    forward = leakage.rank_findings(leakage._stop_findings({"stops": rows}))
    backward = leakage.rank_findings(leakage._stop_findings({"stops": list(reversed(rows))}))
    assert [f.dedupe_key for f in forward] == [f.dedupe_key for f in backward]


def test_the_roll_up_counts_what_was_held_back_and_promises_it():
    """The one thing the summary must never imply is that anything was dropped."""
    held = leakage._stop_findings(
        {"stops": [_stop_row(MIDDAY_UTC, lng=BASE_LNG + 0.03 * i) for i in range(4)]}
    ) + leakage._fraud_findings({"events": [_fraud_row(log_id="log-a")]})

    alert = leakage._summary_alert(held, "2026-09-02")
    assert "Yana 5 ta" in alert.title
    assert "Ruxsatsiz to'xtash — 4 ta" in alert.body
    assert "Shubhali yoqilg'i quyish — 1 ta" in alert.body
    assert "keyingi tekshiruvlarda yuboriladi" in alert.body
    # Per day, not per run: the owner needs to know a backlog exists once.
    assert alert.dedupe_key == "leakage:summary:2026-09-02"
    assert alert.dedupe_ttl_hours == 24


def test_leakage_is_never_critical():
    """Critical bypasses quiet hours. Money already lost is not more recoverable
    at 03:00, and an owner woken for it mutes the bot."""
    alert = leakage._summary_alert(
        leakage._stop_findings({"stops": [_stop_row(MIDDAY_UTC)]}), "2026-09-02"
    )
    assert alert.severity is AlertSeverity.warning
    assert alert.kind is AlertKind.leakage


def test_a_station_name_is_escaped_into_the_body():
    """Bodies are handed to the bus as ready HTML and are not escaped again, so
    anything coming from a driver's typing has to be escaped here."""
    body = leakage._fraud_findings(
        {"events": [_fraud_row(log_id="log-a", station="Neft & <Gaz>")]}
    )[0].body
    assert "Neft &amp; &lt;Gaz&gt;" in body


# ── End to end, against the database ─────────────────────────────────────


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


async def _org_with_chat(db, name: str = "Leak Co", chat_id: str = "700001") -> uuid.UUID:
    org = Organization(name=name)
    db.add(org)
    await db.flush()
    db.add(
        TelegramAccount(
            org_id=org.id,
            token=uuid.uuid4().hex,
            chat_id=chat_id,
            min_severity=AlertSeverity.info,
            muted_kinds=[],
            # Explicitly no quiet window: the defaults are 22→07 and the suite
            # must not start passing or failing with the wall clock.
            quiet_from_hour=None,
            quiet_to_hour=None,
        )
    )
    await db.commit()
    return org.id


async def _truck(db, org_id: uuid.UUID, plate: str) -> uuid.UUID:
    truck = Truck(org_id=org_id, name=f"Truck {plate}", plate_number=plate)
    db.add(truck)
    await db.commit()
    return truck.id


async def _park(db, truck_id: uuid.UUID, *, days_ago: int, lng: float, minutes: int = 40) -> None:
    """A stop long enough to clear MIN_STOP_MINUTES, outside every geofence."""
    start = datetime.now(timezone.utc) - timedelta(days=days_ago)
    for step in range(minutes // 5 + 1):
        db.add(
            TruckLocationHistory(
                truck_id=truck_id,
                latitude=BASE_LAT,
                longitude=lng,
                speed=0,
                recorded_at=start + timedelta(minutes=5 * step),
            )
        )
    await db.commit()


async def _oversized_fill(db, truck_id: uuid.UUID) -> None:
    """A fill bigger than any truck's tank — the unambiguous fraud signal."""
    db.add(
        FuelLog(
            truck_id=truck_id,
            liters=1200,
            cost_per_liter=10_000,
            total_cost=12_000_000,
            fuel_station="UzGazOil",
            filled_at=datetime.now(timezone.utc) - timedelta(days=1),
        )
    )
    await db.commit()


async def test_a_new_stop_and_a_bad_fill_reach_the_owner(db, captured_sends):
    org_id = await _org_with_chat(db)
    truck_id = await _truck(db, org_id, "01A700AA")
    await _park(db, truck_id, days_ago=2, lng=BASE_LNG)
    await _oversized_fill(db, truck_id)

    assert await leakage.run(db) == 2
    texts = "\n".join(text for _, text in captured_sends)
    assert "Ruxsatsiz to'xtash" in texts
    assert "Shubhali yoqilg'i quyish" in texts
    assert "01A700AA" in texts


async def test_the_next_tick_says_nothing_new(db, captured_sends):
    """The window has not moved on; the findings are the same findings. Ticking
    every fifteen minutes, a broken key here is ninety-six messages a day."""
    org_id = await _org_with_chat(db)
    truck_id = await _truck(db, org_id, "01A701AA")
    await _park(db, truck_id, days_ago=2, lng=BASE_LNG)

    assert await leakage.run(db) == 1
    assert await leakage.run(db) == 0
    assert await leakage.run(db) == 0
    assert len(captured_sends) == 1


async def test_one_run_caps_the_alerts_and_reports_the_remainder(db, captured_sends):
    org_id = await _org_with_chat(db)
    for i in range(leakage.MAX_ALERTS_PER_ORG + 2):
        truck_id = await _truck(db, org_id, f"01A72{i}AA")
        await _park(db, truck_id, days_ago=2, lng=BASE_LNG + 0.05 * i)

    sent = await leakage.run(db)

    assert sent == leakage.MAX_ALERTS_PER_ORG + 1  # the five, plus one roll-up
    assert "Yana 2 ta" in captured_sends[-1][1]


async def test_what_the_cap_held_back_arrives_on_the_next_run(db, captured_sends):
    """The cap paces delivery; it must never be a silent drop. Held-back
    findings are left unrecorded precisely so the next tick still sees them."""
    org_id = await _org_with_chat(db)
    plates = []
    for i in range(leakage.MAX_ALERTS_PER_ORG + 2):
        plates.append(f"01A73{i}AA")
        truck_id = await _truck(db, org_id, plates[-1])
        await _park(db, truck_id, days_ago=2, lng=BASE_LNG + 0.05 * i)

    await leakage.run(db)
    first_round = "\n".join(text for _, text in captured_sends)
    missing = [plate for plate in plates if plate not in first_round]
    assert len(missing) == 2

    assert await leakage.run(db) == 2
    second_round = "\n".join(text for _, text in captured_sends[-2:])
    assert all(plate in second_round for plate in missing)


async def test_the_roll_up_is_not_repeated_while_the_backlog_drains(db, captured_sends):
    """One "there is more" line per day. Repeating it every tick is the noise
    the cap exists to prevent."""
    org_id = await _org_with_chat(db)
    for i in range(leakage.MAX_ALERTS_PER_ORG * 2 + 2):
        truck_id = await _truck(db, org_id, f"01A74{i}AA")
        await _park(db, truck_id, days_ago=2, lng=BASE_LNG + 0.05 * i)

    await leakage.run(db)
    await leakage.run(db)
    assert sum(1 for _, text in captured_sends if "Yana" in text) == 1


async def test_findings_never_cross_organizations(db, captured_sends):
    """The tenancy boundary, on the one path that leaves the building."""
    org_a = await _org_with_chat(db, name="Watched Co", chat_id="700001")
    org_b = await _org_with_chat(db, name="Other Co", chat_id="700002")
    truck_a = await _truck(db, org_a, "01A750AA")
    truck_b = await _truck(db, org_b, "01A751BB")
    await _park(db, truck_a, days_ago=2, lng=BASE_LNG)
    await _park(db, truck_b, days_ago=2, lng=BASE_LNG + 0.05)

    await leakage.run(db)

    for chat_id, text in captured_sends:
        assert ("01A750AA" in text) == (chat_id == "700001")
        assert ("01A751BB" in text) == (chat_id == "700002")


async def test_an_org_with_no_linked_chat_is_never_scanned(db, captured_sends, monkeypatch):
    """The GPS scan streams every position row in the window. Paying for it on
    behalf of a company that cannot be messaged is the most expensive way in
    this codebase to produce nothing."""
    org = Organization(name="Unlinked Co")
    db.add(org)
    await db.commit()
    truck_id = await _truck(db, org.id, "01A760AA")
    await _park(db, truck_id, days_ago=2, lng=BASE_LNG)

    scanned: list[uuid.UUID] = []

    async def _spy(session, start, end, org_id):
        scanned.append(org_id)
        return {}

    monkeypatch.setattr(leakage, "scan_tracks", _spy)
    assert await leakage.run(db) == 0
    assert scanned == []


async def test_a_deactivated_chat_stops_the_scan_too(db, captured_sends, monkeypatch):
    """/stop and a blocked bot both land here; neither should keep costing a scan."""
    org_id = await _org_with_chat(db)
    account = (await db.execute(select(TelegramAccount))).scalar_one()
    account.is_active = False
    await db.commit()

    scanned: list[uuid.UUID] = []

    async def _spy(session, start, end, org_id):
        scanned.append(org_id)
        return {}

    monkeypatch.setattr(leakage, "scan_tracks", _spy)
    assert await leakage.run(db) == 0
    assert scanned == []


async def test_one_broken_org_does_not_cost_the_others_their_tick(db, captured_sends, monkeypatch):
    """``run`` is a scheduler job: whatever it finds, it has to come back."""
    broken = await _org_with_chat(db, name="Broken Co", chat_id="700001")
    healthy = await _org_with_chat(db, name="Healthy Co", chat_id="700002")
    truck_id = await _truck(db, healthy, "01A770AA")
    await _park(db, truck_id, days_ago=2, lng=BASE_LNG)

    real_scan = leakage.scan_tracks

    async def _explode_for_broken(session, start, end, org_id):
        if org_id == broken:
            raise RuntimeError("gps scan exploded")
        return await real_scan(session, start, end, org_id)

    monkeypatch.setattr(leakage, "scan_tracks", _explode_for_broken)

    assert await leakage.run(db) == 1
    assert [chat_id for chat_id, _ in captured_sends] == ["700002"]


async def test_nothing_is_recorded_when_telegram_is_not_configured(db, monkeypatch):
    """No bot token means no owner to tell — and the dedupe log must stay empty,
    or every finding would be marked as reported before anyone could read it."""
    monkeypatch.setattr(settings, "telegram_bot_token", "", raising=False)
    org_id = await _org_with_chat(db)
    truck_id = await _truck(db, org_id, "01A780AA")
    await _park(db, truck_id, days_ago=2, lng=BASE_LNG)

    assert await leakage.run(db) == 0
    assert (await db.execute(select(NotificationLog))).scalars().all() == []


async def test_a_finding_older_than_the_window_falls_out_instead_of_repeating(
    db, captured_sends
):
    """The TTL outlives the window on purpose: a stop stays visible for seven
    days and must be announced on the first of them only."""
    org_id = await _org_with_chat(db)
    truck_id = await _truck(db, org_id, "01A790AA")
    await _park(db, truck_id, days_ago=2, lng=BASE_LNG)

    assert await leakage.run(db) == 1
    row = (await db.execute(select(NotificationLog))).scalar_one()
    # Six days on, the stop is still inside the window. Nothing may be resent.
    row.sent_at = datetime.now(timezone.utc) - timedelta(days=6)
    await db.commit()
    assert await leakage.run(db) == 0
