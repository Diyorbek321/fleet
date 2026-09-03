"""The question-answering agent: what it may say, and whose data it may say it about.

Two failures matter here and neither of them looks like an error message.

The first is a wrong number. The model writes the sentence, so nothing stops it
from adding two figures together, rounding a litre count or inventing one
outright — and a number in a money answer is believed. The verification tests
below pin the gate that throws such an answer away, including the two cases that
make a naive gate useless: a plate is not a measurement, and a total the model
computed itself is not a fact.

The second is the wrong company. ``trucks.plate_number`` is unique across the
whole table, so every lookup that starts from a plate is one missing ``org_id``
away from answering questions about a competitor's fleet. Those tests seed two
organizations and ask one of them about the other's truck.

Everything else — routing, refusal, no API key, a dead provider — is about the
owner always learning which of the three happened instead of hearing silence.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest

from app.core.config import settings
from app.models.enums import (
    TripReportCountry,
    TripReportExpenseCategory,
    TripStatus,
)
from app.models.maintenance import FuelLog
from app.models.organizations import Organization
from app.models.owner_alerts import AlertSeverity, TelegramAccount
from app.models.trip_reports import TripCountryExpenseLine, TripExpenseReport
from app.models.trips import Trip
from app.models.trucks import Truck, TruckLocation
from app.services.owner_alerts import ask, commands
from app.services.owner_alerts.ask import Facts, Figure

MID_AUGUST = datetime(2026, 8, 20, 9, 0, tzinfo=timezone.utc)
MID_JULY = datetime(2026, 7, 20, 9, 0, tzinfo=timezone.utc)


def _figure(text: str, value: float) -> Figure:
    return Figure(key="k", label="l", text=text, value=value)


# ── Language ─────────────────────────────────────────────────────────────


def test_a_russian_question_is_answered_in_russian():
    assert ask.detect_language("кто больше всех потратил топлива?") == "ru"


def test_a_latin_uzbek_question_is_answered_in_uzbek():
    assert ask.detect_language("hozir qaysi mashinalar yo'lda?") == "uz"


def test_uzbek_written_in_cyrillic_is_not_mistaken_for_russian():
    """An owner writing Uzbek in Cyrillic is a real customer, and answering them
    in Russian because their alphabet looked Russian reads as a foreign product."""
    assert ask.detect_language("қайси машиналар йўлда?") == "uz"


def test_a_plate_does_not_drag_a_question_into_the_wrong_language():
    """Latin plates appear in Russian questions; they must not outvote the words."""
    assert ask.detect_language("где сейчас 01A123BC?") == "ru"


# ── Routing ──────────────────────────────────────────────────────────────


def test_json_fenced_in_a_code_block_still_routes():
    """Models wrap JSON in ``` and add a sentence about it. That is packaging,
    not disagreement, and refusing it would refuse a correct route."""
    raw = 'Sure!\n```json\n{"capability": "truck_position", "arguments": {"plate": "01A123BC"}}\n```'
    assert ask.parse_intent(raw) == ("truck_position", {"plate": "01A123BC"})


def test_an_answer_with_no_json_at_all_routes_nowhere():
    assert ask.parse_intent("I think you want the fuel report") == (None, {})


def test_a_null_capability_routes_nowhere():
    """The model's own way of saying "out of scope", which must survive as one."""
    assert ask.parse_intent('{"capability": null}') == (None, {})


def test_arguments_that_are_not_an_object_are_dropped_not_trusted():
    assert ask.parse_intent('{"capability": "leakage", "arguments": "7 days"}') == ("leakage", {})


def test_a_month_becomes_the_whole_month():
    assert ask._arg_month({"month": "2026-08"}) == (date(2026, 8, 1), date(2026, 8, 31))


def test_december_does_not_roll_into_month_thirteen():
    assert ask._arg_month({"month": "2026-12"}) == (date(2026, 12, 1), date(2026, 12, 31))


def test_a_month_that_is_not_a_month_is_no_month():
    assert ask._arg_month({"month": "avgust"}) is None
    assert ask._arg_month({}) is None


def test_a_window_the_model_invented_is_clamped_not_obeyed():
    """A GPS scan runs inside the webhook request; "days: 3650" must not start one."""
    assert ask._arg_days({"days": 3650}, default=7, maximum=30) == 30
    assert ask._arg_days({"days": 0}, default=7, maximum=30) == 1
    assert ask._arg_days({"days": "haftalik"}, default=7, maximum=30) == 7


# ── Number verification ──────────────────────────────────────────────────


def test_a_figure_copied_exactly_is_accepted():
    facts = Facts(lines=["Yoqilg'i: 1 200 l"], figures=[_figure("1 200 l", 1200)])
    assert ask.invented_numbers("Kecha 1 200 l yoqilg'i quyilgan.", facts) == []


def test_a_number_nobody_measured_is_caught():
    facts = Facts(lines=["Yoqilg'i: 1 200 l"], figures=[_figure("1 200 l", 1200)])
    assert ask.invented_numbers("Kecha 1 850 l quyilgan.", facts) == ["1 850"]


def test_a_total_the_model_added_up_itself_is_caught():
    """The dangerous case, because the sentence reads perfectly. Two real figures
    plus one derived one is an answer whose arithmetic nobody checked."""
    facts = Facts(
        lines=["KZ: 400 000 so'm", "RU: 600 000 so'm"],
        figures=[_figure("400 000 so'm", 400_000), _figure("600 000 so'm", 600_000)],
    )
    assert ask.invented_numbers("Jami 1 000 000 so'm sarflandi.", facts) == ["1 000 000"]


def test_naming_the_truck_is_not_inventing_a_number():
    """A plate reads to a number scanner as 01 and 123. Without the literal list
    every correct answer that names the truck would be thrown away."""
    facts = Facts(
        lines=["📍 01A123BC · Volvo"],
        figures=[_figure("62 km/soat", 62)],
        literals=["01A123BC", "Volvo"],
    )
    assert ask.invented_numbers("01A123BC hozir 62 km/soat tezlikda.", facts) == []


def test_quoting_the_date_range_is_not_inventing_a_number():
    facts = Facts(
        lines=["Davr: 01.08.2026 – 31.08.2026"],
        figures=[],
        literals=["01.08.2026", "31.08.2026"],
    )
    assert ask.invented_numbers("01.08.2026 – 31.08.2026 oralig'ida.", facts) == []


# ── Fixtures ─────────────────────────────────────────────────────────────


class _Model:
    """A scripted stand-in for the chat completion endpoint.

    Answering one question costs two calls — route, then phrase — and a test
    that scripts only the first gets an empty second, which is exactly the
    "no usable prose" path that ships the fact sheet. That makes the sheet the
    default thing under test and the model's prose the exception.
    """

    def __init__(self) -> None:
        self.replies: list[str] = []
        self.calls: list[tuple[str, str]] = []
        self.error: Exception | None = None

    def script(self, *replies: str) -> None:
        self.replies.extend(replies)

    async def __call__(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        if self.error is not None:
            raise self.error
        return self.replies.pop(0) if self.replies else ""


@pytest.fixture
def model(monkeypatch) -> _Model:
    stub = _Model()
    monkeypatch.setattr(settings, "ai_api_key", "test-key", raising=False)
    monkeypatch.setattr(ask, "call_chat_completion", stub)
    return stub


async def _org(db, *, name: str = "Silk Road", chat_id: str | None = "810001", **kwargs) -> uuid.UUID:
    org = Organization(name=name, usd_to_kzt=470, usd_to_rub=90, usd_to_uzs=12500, **kwargs)
    db.add(org)
    await db.flush()
    if chat_id is not None:
        db.add(
            TelegramAccount(
                org_id=org.id,
                token=uuid.uuid4().hex,
                chat_id=chat_id,
                min_severity=AlertSeverity.info,
                quiet_from_hour=None,
                quiet_to_hour=None,
            )
        )
    await db.commit()
    return org.id


async def _truck(db, org_id: uuid.UUID, plate: str, *, name: str = "Volvo") -> Truck:
    truck = Truck(org_id=org_id, name=name, plate_number=plate)
    db.add(truck)
    await db.commit()
    return truck


async def _trip_on_the_road(db, org_id, truck: Truck | None = None, **kwargs) -> Trip:
    trip = Trip(
        org_id=org_id,
        reference=f"TR-{uuid.uuid4().hex[:8]}",
        status=TripStatus.en_route,
        truck_id=truck.id if truck else None,
        origin_name=kwargs.pop("origin_name", "Toshkent"),
        destination_name=kwargs.pop("destination_name", "Moskva"),
        started_at=datetime.now(timezone.utc),
        **kwargs,
    )
    db.add(trip)
    await db.commit()
    return trip


def _ctx(db, org_id: uuid.UUID, *, lang: str = "uz", **args) -> ask.Ctx:
    return ask.Ctx(db=db, org_id=org_id, lang=lang, args=args)


# ── Capabilities: what they say, and whose data they say it from ─────────


async def test_only_this_companys_trucks_are_on_the_road(db):
    """The count is the figure an owner checks by looking out of the window;
    a neighbour's truck in it is both wrong and a data leak."""
    mine = await _org(db, name="Mine")
    theirs = await _org(db, name="Theirs", chat_id=None)
    await _trip_on_the_road(db, mine, await _truck(db, mine, "01A111AA"))
    await _trip_on_the_road(db, theirs, await _truck(db, theirs, "01B222BB"))

    sheet = (await ask.cap_active_trips(_ctx(db, mine))).sheet()

    assert "01A111AA" in sheet
    assert "01B222BB" not in sheet
    assert "🚚 Hozir yo'lda: 1 ta" in sheet


async def test_a_parked_fleet_is_reported_as_zero_not_as_nothing(db):
    """"Hozir yo'lda: 0 ta" is a fact about the fleet; an empty answer is a bug
    the owner cannot tell apart from a broken bot."""
    org_id = await _org(db)
    sheet = (await ask.cap_active_trips(_ctx(db, org_id))).sheet()
    assert "0 ta" in sheet


async def test_a_plate_belonging_to_another_company_is_simply_not_found(db):
    """The load-bearing tenancy case. ``plate_number`` is unique table-wide, so
    the unscoped version of this lookup answers with a competitor's truck."""
    mine = await _org(db, name="Mine")
    theirs = await _org(db, name="Theirs", chat_id=None)
    neighbour = await _truck(db, theirs, "01B222BB")
    db.add(
        TruckLocation(truck_id=neighbour.id, latitude=41.3, longitude=69.2, speed=60)
    )
    await db.commit()

    facts = await ask.cap_truck_position(_ctx(db, mine, plate="01B222BB"))

    assert "topilmadi" in facts.sheet()
    assert "41" not in facts.sheet()


async def test_a_position_answer_carries_the_plate_the_speed_and_the_moment(db):
    org_id = await _org(db)
    truck = await _truck(db, org_id, "01A123BC")
    db.add(
        TruckLocation(
            truck_id=truck.id,
            latitude=41.31083,
            longitude=69.24065,
            speed=62,
            address="M39, Sirdaryo",
            recorded_at=datetime(2026, 9, 3, 9, 5, tzinfo=timezone.utc),
        )
    )
    await db.commit()

    sheet = (await ask.cap_truck_position(_ctx(db, org_id, plate="01A123BC"))).sheet()

    assert "01A123BC" in sheet
    assert "62 km/soat" in sheet
    assert "41.31083, 69.24065" in sheet
    # 09:05 UTC is 14:05 in Tashkent, which is the clock the owner reads.
    assert "03.09.2026 14:05" in sheet
    assert "M39, Sirdaryo" in sheet


async def test_a_plate_typed_with_spaces_still_finds_the_truck(db):
    """Owners type plates from memory, not from the registration document."""
    org_id = await _org(db)
    await _truck(db, org_id, "01A123BC")
    facts = await ask.cap_truck_position(_ctx(db, org_id, plate="01 A 123 BC"))
    assert "topilmadi" not in facts.sheet()


async def test_a_truck_with_no_gps_says_so_instead_of_guessing(db):
    org_id = await _org(db)
    await _truck(db, org_id, "01A123BC")
    sheet = (await ask.cap_truck_position(_ctx(db, org_id, plate="01A123BC"))).sheet()
    assert "Joylashuv ma'lumoti yo'q" in sheet


async def test_country_spending_answers_for_the_month_that_was_asked_about(db):
    """"Avgustda qancha yedi" means August. A window that quietly spans ninety
    days answers a different question with a bigger number."""
    org_id = await _org(db)
    truck = await _truck(db, org_id, "01A123BC")
    for when, amount in ((MID_AUGUST, 450_000), (MID_JULY, 900_000)):
        trip = Trip(
            org_id=org_id,
            reference=f"TR-{uuid.uuid4().hex[:8]}",
            status=TripStatus.delivered,
            truck_id=truck.id,
            delivered_at=when,
        )
        db.add(trip)
        await db.flush()
        report = TripExpenseReport(org_id=org_id, trip_id=trip.id, report_date=when.date())
        db.add(report)
        await db.flush()
        db.add(
            TripCountryExpenseLine(
                report_id=report.id,
                country=TripReportCountry.kz,
                category=TripReportExpenseCategory.platon,
                amount=amount,
            )
        )
    await db.commit()

    sheet = (
        await ask.cap_country_spending(_ctx(db, org_id, plate="01A123BC", month="2026-08"))
    ).sheet()

    assert "Qozog'iston: 450 000 KZT" in sheet
    assert "900 000" not in sheet
    assert "957 USD" in sheet  # 450 000 / 470, at the org's own rate
    assert "01.08.2026 – 31.08.2026" in sheet


async def test_a_country_with_no_rate_keeps_its_own_currency_and_says_why(db):
    """The USD column going empty is the honest answer; a converted number at a
    rate nobody chose is the dishonest one."""
    org = Organization(name="No Rates")
    db.add(org)
    await db.flush()
    trip = Trip(
        org_id=org.id,
        reference="TR-NORATE",
        status=TripStatus.delivered,
        delivered_at=MID_AUGUST,
    )
    db.add(trip)
    await db.flush()
    report = TripExpenseReport(org_id=org.id, trip_id=trip.id, report_date=MID_AUGUST.date())
    db.add(report)
    await db.flush()
    db.add(
        TripCountryExpenseLine(
            report_id=report.id,
            country=TripReportCountry.kz,
            category=TripReportExpenseCategory.platon,
            amount=450_000,
        )
    )
    await db.commit()

    sheet = (await ask.cap_country_spending(_ctx(db, org.id, month="2026-08"))).sheet()

    assert "450 000 KZT (Kurs kiritilmagan, USD to'liq emas)" in sheet
    assert "≈" not in sheet  # nothing was converted, so no equivalence is claimed


async def test_fuel_ranking_puts_the_thirstiest_truck_first(db):
    org_id = await _org(db)
    thirsty = await _truck(db, org_id, "01A111AA", name="Volvo")
    frugal = await _truck(db, org_id, "01A222BB", name="MAN")
    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    db.add_all(
        [
            FuelLog(truck_id=thirsty.id, liters=900, cost_per_liter=12_000,
                    total_cost=10_800_000, filled_at=yesterday),
            FuelLog(truck_id=frugal.id, liters=300, cost_per_liter=12_000,
                    total_cost=3_600_000, filled_at=yesterday),
        ]
    )
    await db.commit()

    lines = (await ask.cap_fuel_ranking(_ctx(db, org_id, days=30))).lines

    assert lines[1].startswith("1. Volvo (01A111AA)")
    assert "900 l" in lines[1] and "10 800 000 so'm" in lines[1]
    assert lines[2].startswith("2. MAN (01A222BB)")


async def test_another_companys_fill_ups_are_not_in_the_ranking(db):
    mine = await _org(db, name="Mine")
    theirs = await _org(db, name="Theirs", chat_id=None)
    neighbour = await _truck(db, theirs, "01B999ZZ", name="Kamaz")
    db.add(
        FuelLog(
            truck_id=neighbour.id,
            liters=5000,
            cost_per_liter=12_000,
            total_cost=60_000_000,
            filled_at=datetime.now(timezone.utc) - timedelta(days=1),
        )
    )
    await db.commit()

    sheet = (await ask.cap_fuel_ranking(_ctx(db, mine))).sheet()

    assert "Kamaz" not in sheet
    assert "Bu davrda yoqilg'i quyilmagan." in sheet


async def test_the_leakage_answer_states_the_window_it_actually_measured(db):
    """Analytics clamps the request to the period GPS history is kept for. An
    answer that quotes the requested window instead describes a scan nobody ran."""
    org_id = await _org(db)
    facts = await ask.cap_leakage(_ctx(db, org_id, days=7))
    assert "7 kun" in facts.lines[0]
    assert "Ruxsatsiz to'xtashlar: 0 ta" in facts.sheet()


async def test_a_russian_question_gets_russian_labels_from_the_template(db):
    """The templated path is the normal path wherever no AI key is configured,
    so it has to speak the asker's language on its own."""
    org_id = await _org(db)
    sheet = (await ask.cap_leakage(_ctx(db, org_id, lang="ru"))).sheet()
    assert "🔎 Потери" in sheet
    assert "Простой" in sheet


# ── End to end, through the chat ─────────────────────────────────────────


async def _accounts(db, chat_id: str) -> list[TelegramAccount]:
    from sqlalchemy import select

    rows = (
        await db.execute(select(TelegramAccount).where(TelegramAccount.chat_id == chat_id))
    ).scalars().all()
    return list(rows)


async def test_the_owner_gets_the_number_we_measured(db, model):
    org_id = await _org(db)
    await _trip_on_the_road(db, org_id, await _truck(db, org_id, "01A111AA"))
    model.script('{"capability": "active_trips"}', "Hozir yo'lda 1 ta mashina bor.")

    reply = await ask.answer_question(db, await _accounts(db, "810001"), "qaysi mashinalar yo'lda?")

    assert reply == "Hozir yo'lda 1 ta mashina bor."


async def test_an_invented_number_costs_the_prose_not_the_answer(db, model):
    """The whole feature rests on this: a wrong number never reaches the owner,
    and what reaches them instead is the same answer stated plainly."""
    org_id = await _org(db)
    await _trip_on_the_road(db, org_id, await _truck(db, org_id, "01A111AA"))
    model.script('{"capability": "active_trips"}', "Hozir yo'lda 7 ta mashina bor.")

    reply = await ask.answer_question(db, await _accounts(db, "810001"), "nechta mashina yo'lda?")

    assert "7 ta" not in reply
    assert "Hozir yo'lda: 1 ta" in reply
    assert "01A111AA" in reply


async def test_a_question_outside_the_capabilities_is_refused_not_guessed(db, model):
    org_id = await _org(db)
    model.script('{"capability": null}')

    reply = await ask.answer_question(
        db, await _accounts(db, "810001"), "kelasi oyda dizel narxi qancha bo'ladi?"
    )

    assert "ayta olmayman" in reply
    assert "/settings" in reply
    assert len(model.calls) == 1  # nothing was measured, so nothing was phrased


async def test_a_capability_the_system_does_not_have_is_refused(db, model):
    """A model that names ``driver_salaries`` has hallucinated a tool. The
    nearest real capability is not an acceptable substitute."""
    org_id = await _org(db)
    model.script('{"capability": "driver_salaries", "arguments": {}}')

    reply = await ask.answer_question(db, await _accounts(db, "810001"), "haydovchilarga qancha to'ladik?")

    assert "ayta olmayman" in reply


async def test_a_russian_question_is_refused_in_russian(db, model):
    org_id = await _org(db)
    model.script('{"capability": null}')
    reply = await ask.answer_question(db, await _accounts(db, "810001"), "какая завтра погода?")
    assert "Пока не могу это сказать." in reply


async def test_without_an_api_key_the_bot_says_so_instead_of_going_quiet(db, monkeypatch):
    """Most deployments will never set a key. Silence there reads as a broken
    bot; one honest line reads as a feature nobody switched on."""
    monkeypatch.setattr(settings, "ai_api_key", "", raising=False)
    await _org(db)

    reply = await ask.answer_question(db, await _accounts(db, "810001"), "mashinalar qayerda?")

    assert "yoqilmagan" in reply
    # An owner who cannot get an answer must still be told what the bot can do;
    # this reply is the only place /settings and /stop are named.
    assert "/settings" in reply


async def test_a_dead_provider_reads_as_try_again(db, model):
    org_id = await _org(db)
    model.error = RuntimeError("provider is down")

    reply = await ask.answer_question(db, await _accounts(db, "810001"), "mashinalar qayerda?")

    assert "Birozdan keyin qayta yozing" in reply


async def test_a_suspended_company_gets_no_numbers(db, model):
    """``is_active`` is the billing switch. A customer locked out of the panel
    must not still be able to read the same figures out of the bot."""
    org_id = await _org(db, name="Unpaid", is_active=False)
    await _trip_on_the_road(db, org_id, await _truck(db, org_id, "01A111AA"))
    model.script('{"capability": "active_trips"}', "Hozir yo'lda 1 ta mashina bor.")

    reply = await ask.answer_question(db, await _accounts(db, "810001"), "nechta mashina yo'lda?")

    assert "faol emas" in reply
    assert model.calls == []


async def test_a_truck_name_with_markup_in_it_cannot_reach_telegram_raw(db, model):
    """The reply is sent with parse_mode=HTML, so an unescaped ``<`` in a name
    the customer chose breaks the message — or worse, formats it."""
    org_id = await _org(db)
    truck = await _truck(db, org_id, "01A111AA", name="Neft & <Gaz>")
    db.add(TruckLocation(truck_id=truck.id, latitude=41.3, longitude=69.2, speed=0))
    await db.commit()
    model.script('{"capability": "truck_position", "arguments": {"plate": "01A111AA"}}')

    reply = await ask.answer_question(db, await _accounts(db, "810001"), "01A111AA qayerda?")

    assert "Neft &amp; &lt;Gaz&gt;" in reply


async def test_two_companies_in_one_chat_are_told_apart(db, model):
    """One chat, one set of books. Merging them produces totals that belong to
    neither business, so the answer names the company it is about."""
    first = await _org(db, name="Birinchi", chat_id=None)
    second = await _org(db, name="Ikkinchi", chat_id=None)
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for index, org_id in enumerate((first, second)):
        db.add(
            TelegramAccount(
                org_id=org_id,
                token=uuid.uuid4().hex,
                chat_id="810002",
                created_at=base + timedelta(days=index),
                quiet_from_hour=None,
                quiet_to_hour=None,
            )
        )
    await db.commit()
    await _trip_on_the_road(db, first, await _truck(db, first, "01A111AA"))
    model.script('{"capability": "active_trips"}')

    reply = await ask.answer_question(db, await _accounts(db, "810002"), "nechta mashina yo'lda?")

    assert reply.startswith("<b>Birinchi</b>")
    assert "01A111AA" in reply


# ── The dispatch table ───────────────────────────────────────────────────


async def test_free_text_from_an_owner_reaches_the_agent(db, model):
    """The registration itself: without it every question falls through to the
    generic help text and the feature does not exist."""
    org_id = await _org(db)
    await _trip_on_the_road(db, org_id, await _truck(db, org_id, "01A111AA"))
    model.script('{"capability": "active_trips"}', "Bitta mashina yo'lda.")

    reply = await commands.handle_owner_message(db, "810001", "qaysi mashinalar yo'lda?")

    assert reply == "Bitta mashina yo'lda."


async def test_the_commands_that_were_here_first_still_answer(db, model):
    """A fallback that swallowed /settings would take the owner's only way to
    see what the bot is set to."""
    await _org(db)

    assert "Sozlamalar" in await commands.handle_owner_message(db, "810001", "/settings")
    assert "Buyruqlar" in await commands.handle_owner_message(db, "810001", "/help")
    assert "to'xtatildi" in await commands.handle_owner_message(db, "810001", "/stop")


async def test_a_chat_with_no_owner_link_is_still_none_of_our_business(db, model):
    """The bot also serves cargo owners subscribed to a single trip. Claiming
    their messages would break that flow."""
    await _org(db)
    assert await commands.handle_owner_message(db, "999999", "salom") is None


async def test_a_message_with_no_words_is_left_alone(db, model):
    """A forwarded photo arrives as an empty caption; there is no question in it."""
    await _org(db)
    accounts = await _accounts(db, "810001")
    assert await ask.answer_question(db, accounts, "   ") is None


# ── Rate limiting ────────────────────────────────────────────────────────
#
# Every question spends two paid model calls and blocks the webhook — an
# endpoint shared by every tenant — until both return. Unthrottled, one chat is
# both a bill and an outage waiting to happen; the limiter already on the
# webhook is keyed by Telegram's own calling IP, so it caps all customers
# together and no individual chat at all.


@pytest.fixture(autouse=True)
def _fresh_rate_limit_bucket():
    """The bucket is module state, so a test that fills it must not spend the
    next one's budget."""
    ask._ask_calls.clear()
    yield
    ask._ask_calls.clear()


def test_a_chat_may_ask_up_to_its_hourly_allowance():
    for _ in range(ask.ASK_MAX_PER_HOUR):
        assert ask._within_rate_limit("810001") is True
    assert ask._within_rate_limit("810001") is False


def test_one_chat_running_hot_does_not_spend_anothers_budget():
    """Keyed on the chat, not the org: one noisy phone must not silence the
    owner's other device — or another company entirely."""
    for _ in range(ask.ASK_MAX_PER_HOUR):
        ask._within_rate_limit("810001")

    assert ask._within_rate_limit("810002") is True


def test_the_allowance_refills_as_the_window_slides():
    """A limit that never forgives is a ban."""
    now = datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)
    for _ in range(ask.ASK_MAX_PER_HOUR):
        ask._within_rate_limit("810001", now=now)
    assert ask._within_rate_limit("810001", now=now) is False

    assert ask._within_rate_limit("810001", now=now + timedelta(hours=1, minutes=1)) is True


def test_a_refused_question_does_not_consume_another_slot():
    """Otherwise a chat that keeps typing after being told to wait can never
    climb back out of the hole."""
    now = datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)
    for _ in range(ask.ASK_MAX_PER_HOUR):
        ask._within_rate_limit("810001", now=now)
    for _ in range(5):
        ask._within_rate_limit("810001", now=now)

    # Exactly the allowance is on record, so the window still clears on time.
    assert len(ask._ask_calls["810001"]) == ask.ASK_MAX_PER_HOUR


async def test_the_owner_is_told_to_wait_rather_than_ignored(db, model):
    """Silence reads as a broken bot; one line reads as a busy one."""
    org_id = await _org(db)
    await _trip_on_the_road(db, org_id, await _truck(db, org_id, "01A111AA"))
    accounts = await _accounts(db, "810001")
    for _ in range(ask.ASK_MAX_PER_HOUR):
        ask._within_rate_limit("810001")

    reply = await ask.answer_question(db, accounts, "qaysi mashinalar yo'lda?")

    assert reply is not None
    assert "qayta urinib" in reply


async def test_a_throttled_question_never_reaches_the_model(db, model):
    """The whole point is the calls not made — a limiter that still pays for
    the answer is decoration."""
    org_id = await _org(db)
    await _trip_on_the_road(db, org_id, await _truck(db, org_id, "01A111AA"))
    accounts = await _accounts(db, "810001")
    for _ in range(ask.ASK_MAX_PER_HOUR):
        ask._within_rate_limit("810001")

    before = len(model.calls)
    await ask.answer_question(db, accounts, "qaysi mashinalar yo'lda?")

    assert len(model.calls) == before
