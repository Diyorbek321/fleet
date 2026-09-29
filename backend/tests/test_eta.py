"""The arrival estimate, and the card it ends up in.

The pure half is tested without a database on purpose: every rule that decides
a date — how many borders are left, how fast this truck is really going, when
to refuse to answer — is a function of numbers, and a test that has to seed a
tenant to check arithmetic is a test nobody runs while changing the arithmetic.
"""
from datetime import date, datetime, timedelta, timezone

import pytest

from app.models.enums import StagePlace, TripStage
from app.models.trips import Trip
from app.services import eta
from app.services.telegram import format_customer_card, stage_label


# ── Distance and pace ────────────────────────────────────────────────────


def test_road_distance_is_longer_than_the_crow_flies():
    """Tashkent to Almaty is ~600 km of road over ~480 km of air."""
    km = eta.road_km(41.2995, 69.2401, 43.2220, 76.8512)
    assert 700 < km < 900


def test_a_truck_that_has_not_moved_a_day_is_given_the_corridor_default():
    """Two hours of GPS says nothing about a week-long run."""
    assert eta.pace_km_per_day(90, timedelta(hours=2)) == eta.DEFAULT_KM_PER_DAY


def test_pace_is_measured_from_the_truck_itself_once_there_is_enough_of_it():
    assert eta.pace_km_per_day(1200, timedelta(days=3)) == pytest.approx(400)


@pytest.mark.parametrize(
    "covered,days,expected",
    [
        (10, 5, eta.MIN_KM_PER_DAY),      # stuck at a border, not slow
        (9000, 3, eta.MAX_KM_PER_DAY),    # GPS artefact, not a rocket
    ],
)
def test_an_impossible_pace_is_clamped_rather_than_believed(covered, days, expected):
    """Dividing by a bad pace puts the arrival in the wrong decade."""
    assert eta.pace_km_per_day(covered, timedelta(days=days)) == expected


# ── How much border is left ──────────────────────────────────────────────


def test_a_trip_with_no_checkpoint_yet_still_has_every_crossing_ahead():
    assert eta.borders_ahead(None, None) == 2


def test_standing_at_the_first_crossing_leaves_both_to_clear():
    assert eta.borders_ahead(TripStage.arrived_border, "uz_kz") == 2


def test_clearing_the_first_crossing_leaves_one():
    assert eta.borders_ahead(TripStage.crossed_border, "uz_kz") == 1


def test_clearing_the_last_crossing_leaves_none():
    assert eta.borders_ahead(TripStage.crossed_border, "kz_ru") == 0


def test_past_customs_there_is_no_border_left_to_count():
    assert eta.borders_ahead(TripStage.left_customs, "ru") == 0


# ── ...counted in the direction the run goes ─────────────────────────────
#
# Customs is in the destination country, so a RU→UZ run meets KZ–RU first and
# UZ–KZ last — the reverse of the order above, which is what a trip with no
# direction on file still gets.


@pytest.mark.parametrize(
    "stage,place,expected",
    [
        (None, None, 2),
        (TripStage.arrived_loading, "ru", 2),
        (TripStage.arrived_border, "kz_ru", 2),
        (TripStage.crossed_border, "kz_ru", 1),
        (TripStage.docs_received_en_route, "kz", 1),
        (TripStage.arrived_border, "uz_kz", 1),
        (TripStage.crossed_border, "uz_kz", 0),
        (TripStage.docs_received_en_route, "uz", 0),
    ],
)
def test_a_run_into_uzbekistan_meets_the_crossings_north_to_south(stage, place, expected):
    assert eta.borders_ahead(stage, place, "ru_uz") == expected


@pytest.mark.parametrize(
    "stage,place,expected",
    [
        (TripStage.arrived_loading, "uz", 2),
        (TripStage.arrived_border, "uz_kz", 2),
        (TripStage.crossed_border, "uz_kz", 1),
        (TripStage.docs_received_en_route, "kz", 1),
        (TripStage.crossed_border, "kz_ru", 0),
        (TripStage.docs_received_en_route, "ru", 0),
    ],
)
def test_a_run_into_russia_meets_them_south_to_north(stage, place, expected):
    assert eta.borders_ahead(stage, place, "uz_ru") == expected


def test_the_enum_place_counts_the_same_as_its_value():
    """The trip row carries a StagePlace, not a bare string."""
    assert eta.borders_ahead(TripStage.crossed_border, StagePlace.kz_ru, "ru_uz") == 1


def test_a_trip_with_no_direction_keeps_the_old_count():
    """Trips created before the direction was recorded are not re-guessed."""
    assert eta.borders_ahead(TripStage.crossed_border, "kz_ru", None) == 0
    assert eta.borders_ahead(TripStage.docs_received_en_route, "kz", None) == 2


def test_borders_still_ahead_push_the_date_out():
    """The queue is most of the week on this corridor; ignoring it would make
    every estimate optimistic by exactly the thing customers complain about."""
    near = eta.model_hours(1000, 500, crossings_ahead=0)
    far = eta.model_hours(1000, 500, crossings_ahead=2)
    assert far - near == pytest.approx(2 * eta.BORDER_HOURS)


# ── The corridor key ─────────────────────────────────────────────────────


def test_the_same_route_typed_two_ways_is_one_corridor():
    """Dispatchers type "Ташкент" one day and "Ташкент, Сергели" the next."""
    a = Trip(origin_name="Тобольск", destination_name="Ташкент")
    b = Trip(origin_name="тобольск ", destination_name="Ташкент, Сергели")
    assert eta.corridor_key(a) == eta.corridor_key(b)


def test_the_reverse_route_is_a_different_corridor():
    """Northbound and southbound do not take the same time, and pooling them
    would hide exactly the asymmetry a customer is asking about."""
    there = Trip(origin_name="Тобольск", destination_name="Ташкент")
    back = Trip(origin_name="Ташкент", destination_name="Тобольск")
    assert eta.corridor_key(there) != eta.corridor_key(back)


# ── Refusing to answer ───────────────────────────────────────────────────


NOW = datetime(2026, 9, 17, 6, 0, tzinfo=timezone.utc)


def _trip(**kw) -> Trip:
    base = dict(
        origin_name="Тобольск",
        origin_lat=58.19,
        origin_lng=68.25,
        destination_name="Ташкент",
        destination_lat=41.29,
        destination_lng=69.24,
        started_at=NOW - timedelta(days=2),
        created_at=NOW - timedelta(days=2),
        current_stage=TripStage.docs_received_en_route,
        current_stage_place=StagePlace.ru,
    )
    base.update(kw)
    return Trip(**base)


@pytest.mark.parametrize(
    "stage",
    [TripStage.arrived_customs, TripStage.left_customs, TripStage.unloaded],
)
async def test_a_load_already_at_customs_is_not_estimated(db, stage):
    """The question has been answered by an event. Printing a prediction beside
    a fact is how a card starts contradicting itself."""
    assert await eta.estimate_customs_arrival(
        db, _trip(current_stage=stage), current_lat=41.0, current_lng=69.0, now=NOW
    ) is None


async def test_a_trip_with_no_destination_gets_no_date(db):
    """Better a card with six lines than a seventh that was invented."""
    trip = _trip(destination_lat=None, destination_lng=None)
    assert await eta.estimate_customs_arrival(
        db, trip, current_lat=55.0, current_lng=68.0, now=NOW
    ) is None


async def test_a_trip_with_no_position_gets_no_date(db):
    assert await eta.estimate_customs_arrival(
        db, _trip(), current_lat=None, current_lng=None, now=NOW
    ) is None


# ── The modelled estimate ────────────────────────────────────────────────


async def test_the_model_answers_a_plausible_date_for_a_real_corridor(db):
    """Tobolsk→Tashkent is ~3000 km of road and two crossings. The customer's
    own example puts that at a week, which is the number to stay near."""
    estimate = await eta.estimate_customs_arrival(
        db,
        _trip(current_stage=None, current_stage_place=None),
        current_lat=58.19,
        current_lng=68.25,
        covered_km=0,
        now=NOW,
    )
    assert estimate is not None
    assert estimate.basis == "model"
    assert not estimate.is_measured
    assert timedelta(days=5) <= estimate.day - NOW.date() <= timedelta(days=10)


async def test_getting_closer_moves_the_date_in(db):
    far = await eta.estimate_customs_arrival(
        db, _trip(), current_lat=58.19, current_lng=68.25, now=NOW
    )
    near = await eta.estimate_customs_arrival(
        db, _trip(), current_lat=43.20, current_lng=68.50, now=NOW
    )
    assert far is not None and near is not None
    assert near.day < far.day


async def test_the_estimate_counts_borders_in_the_trips_direction(db):
    """Just over KZ–RU on the way south, the UZ–KZ queue is still ahead — a
    whole border day the old north-bound count left out."""
    # ~1500 km out: ~83 h of driving lands at 17:00 on day three, and the
    # 14 h queue pushes it past midnight — far enough from either edge to hold.
    at = dict(current_lat=52.0, current_lng=69.0, now=NOW)
    over_kz_ru = dict(current_stage=TripStage.crossed_border, current_stage_place=StagePlace.kz_ru)

    southbound = await eta.estimate_customs_arrival(db, _trip(direction="ru_uz", **over_kz_ru), **at)
    unknown = await eta.estimate_customs_arrival(db, _trip(direction=None, **over_kz_ru), **at)
    assert southbound is not None and unknown is not None
    assert southbound.day > unknown.day


# ── The card ─────────────────────────────────────────────────────────────


def test_the_border_stage_names_the_crossing_not_a_country():
    """"На границе КЗ" does not say whether the truck is leaving Uzbekistan or
    entering Russia, and those are four days apart on the same trip."""
    assert stage_label(TripStage.arrived_border, StagePlace.uz_kz) == "На границе УЗБ–КЗ"
    assert stage_label(TripStage.crossed_border, StagePlace.kz_ru) == "Прошёл границу КЗ–РФ"


def test_the_card_carries_the_lines_the_customer_asked_for():
    text = format_customer_card(
        org_name="АНГРЕН ТЭК",
        reference="Ангрен Тэк-0042",
        origin="Тобольск",
        destination="Ташкент",
        loaded_at=datetime(2026, 9, 17, tzinfo=timezone.utc),
        plate="10 990 NBA",
        place="Казахстан, Яллама",
        lat=41.0,
        lng=68.9,
        eta_customs=date(2026, 9, 24),
    )
    assert "АНГРЕН ТЭК" in text
    assert "Маршрут: <b>Тобольск — Ташкент</b>" in text
    assert "Дата погрузки: 17.09.2026" in text
    assert "ТС: 10 990 NBA" in text
    assert "Яллама" in text
    assert "Ожидаемая дата прибытия на растаможку: <b>24.09.2026</b>" in text


def test_the_card_carries_no_status_line():
    """Deliberately absent. The customer's question is where the load is and
    when it lands; both are on the card, and a status word between them only
    ever prompted "so which is it?" on the phone."""
    text = format_customer_card(
        org_name="X", reference="X-0001", origin=None, destination=None,
        loaded_at=None, plate=None, place="Казахстан, Яллама", lat=41.0, lng=68.9,
        eta_customs=None,
    )
    assert "Статус" not in text


def test_the_map_link_closes_the_card_and_is_dropped_when_unknown():
    """The one actionable line, and the only one that differs per recipient."""
    common = dict(
        org_name="X", reference="X-0001", origin=None, destination=None,
        loaded_at=None, plate=None, place=None, lat=None, lng=None, eta_customs=None,
    )
    linked = format_customer_card(**common, track_url="https://fleet.example/track/abc")
    assert linked.endswith('<a href="https://fleet.example/track/abc">Посмотреть на карте</a>')

    assert "карте" not in format_customer_card(**common)


def test_the_map_link_escapes_its_url():
    """The token reaches the message as an HTML attribute value."""
    text = format_customer_card(
        org_name="X", reference="X-0001", origin=None, destination=None,
        loaded_at=None, plate=None, place=None, lat=None, lng=None, eta_customs=None,
        track_url='https://fleet.example/track/a"onmouseover="x',
    )
    assert 'onmouseover="x' not in text
    assert "&quot;" in text


def test_a_modelled_date_says_so_and_a_measured_one_does_not():
    """A customer plans differently around a formula's guess than around a
    number the fleet has actually hit twenty times."""
    def card(measured: bool) -> str:
        return format_customer_card(
            org_name="X", reference="X-0001", origin=None, destination=None,
            loaded_at=None, plate=None, place=None, lat=None, lng=None,
            eta_customs=date(2026, 9, 24), eta_is_measured=measured,
        )

    assert "ориентировочно" in card(False)
    assert "ориентировочно" not in card(True)


def test_a_line_with_nothing_behind_it_is_dropped_not_dashed():
    """A card padded out with "—" reads as a broken system; four real lines
    read as a status report.

    The location line is the exception and stays: "where is my cargo" is the
    question the card exists to answer, and "not known yet" answers it.
    """
    text = format_customer_card(
        org_name="X", reference="X-0001", origin=None, destination=None,
        loaded_at=None, plate=None, place=None, lat=None, lng=None,
        eta_customs=None,
    )
    assert "Маршрут" not in text
    assert "Дата погрузки" not in text
    assert "\nТС: " not in text
    assert "растаможку" not in text
    assert "Текущее местоположение ТС:" in text


def test_the_card_carries_one_map_link_not_two():
    """The location line's bare-coordinate Google link is a fallback.

    With a tracking page configured the card ends with a link to it, and the
    coordinate link a thumb above — worded almost identically — only made the
    customer ask which of the two was the real one.
    """
    common = dict(
        org_name="X", reference="X-0001", origin=None, destination=None,
        loaded_at=None, plate=None, place="Казахстан, Яллама", lat=41.0, lng=68.9,
        eta_customs=None,
    )
    linked = format_customer_card(**common, track_url="https://fleet.example/track/abc")
    assert linked.count("карте") == 1
    assert "maps.google.com" not in linked

    # Nothing to point at: the coordinate link is the only answer left, so it stays.
    assert "maps.google.com" in format_customer_card(**common)


def test_a_position_with_no_place_still_reaches_the_customer():
    """Geocoder off and a tracking page configured: coordinates in plain text
    rather than a second link, because "where is my cargo" must be answered."""
    text = format_customer_card(
        org_name="X", reference="X-0001", origin=None, destination=None,
        loaded_at=None, plate=None, place=None, lat=41.0, lng=68.9,
        eta_customs=None, track_url="https://fleet.example/track/abc",
    )
    assert "41.0, 68.9" in text
    assert "maps.google.com" not in text


def test_the_drivers_note_sits_above_the_link_not_below_it():
    """The link is the card's one action and has to stay last; a note appended
    after it pushed the thing the customer is meant to tap into the middle."""
    text = format_customer_card(
        org_name="X", reference="X-0001", origin=None, destination=None,
        loaded_at=None, plate=None, place=None, lat=None, lng=None,
        eta_customs=None, note="Стою в очереди на Яллама",
        track_url="https://fleet.example/track/abc",
    )
    assert text.index("очереди") < text.index("track/abc")
    assert text.rstrip().endswith("</a>")


def test_a_note_is_escaped_like_every_other_field():
    text = format_customer_card(
        org_name="X", reference="X-0001", origin=None, destination=None,
        loaded_at=None, plate=None, place=None, lat=None, lng=None,
        eta_customs=None, note="<b>hi</b>",
    )
    assert "<b>hi</b>" not in text
    assert "&lt;b&gt;hi&lt;/b&gt;" in text
