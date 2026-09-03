"""Savol-javob — the owner types a question and their own fleet answers it.

For most owners this chat is the entire product. They will not open a panel to
find out whether a truck is still in Kazakhstan; they will type "01A123BC
qayerda?" at eleven at night. The bar is therefore not "the model said
something plausible" but "the owner can run their company from this window and
never be misled".

**A closed set of capabilities, not a database agent.** The model never sees a
schema, a query or a row — only five named read-only capabilities, one of which
it picks with arguments. Anything it cannot express in that vocabulary is
refused. Query access would eventually answer a question nobody verified, and
one wrong number about money outweighs every right one.

**The organization comes from the chat, never from the model.** ``org_id`` is
read off the :class:`TelegramAccount` row Telegram's own chat id resolved to and
passed to every service call; no argument can change it. The plate lookup is
scoped too — ``trucks.plate_number`` is unique table-wide, so an unscoped one
would cheerfully report another company's truck.

**The numbers are measured here; the model only phrases them.** Each capability
renders a plain-text fact sheet from the existing services, and every digit in
the model's reply is checked back against that sheet by :func:`invented_numbers`
— the gate the morning briefing already runs on. A failed answer ships as the
sheet itself: plainer prose, identical numbers. A fabricated litre count costs
not one bad message but the owner's belief in every number this product has
ever shown them.

**Refusal and silence are different failures.** Out of scope gets an honest
"buni hozircha ayta olmayman" naming what *is* known; a missing ``AI_API_KEY``
says so; a provider outage says try again. The owner always learns which
happened. Language follows the question — Uzbek or Russian — on the templated
path too, since that path is the normal one wherever no AI key is configured.
"""
from __future__ import annotations

import asyncio
import html
import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import logger
from app.models.drivers import Driver
from app.models.enums import TripStatus
from app.models.organizations import Organization
from app.models.owner_alerts import TelegramAccount
from app.models.trips import Trip
from app.models.trucks import Truck, TruckLocation
from app.services.ai_reports import LANGUAGE_NAMES
from app.services.ai_reports import _call_ai as call_chat_completion
from app.services.ai_reports import _gather_fuel as gather_fuel
from app.services.analytics import leakage_summary
from app.services.country_expenses import build_country_expense_report
from app.services.owner_alerts.briefing import Figure, unverified_numbers
from app.services.owner_alerts.commands import register_fallback
from app.services.period_reports import report_tz

__all__ = [
    "CAPABILITIES", "Facts", "answer_question", "build_answer_prompt",
    "build_intent_prompt", "detect_language", "invented_numbers", "parse_intent",
]

# Long enough for any real question, short enough that a pasted wall of text
# cannot turn one message into a large prompt bill (or a prompt-injection
# canvas — the org scoping below is what actually contains that, but there is
# no reason to pay for the attempt).
MAX_QUESTION_CHARS = 400

# This runs inside Telegram's webhook request, not a scheduler tick: two model
# calls at this timeout still answer well inside the webhook's patience, and a
# stalled provider becomes "try again" rather than a hung worker.
AI_TIMEOUT_S = 20.0

# Whatever the bot cannot answer, it still has to say what it *can* do: an
# owner who typed something it does not understand has no other route back to
# /settings and /stop.
_COMMAND_HINT = "/settings · /stop · /help"

# Two paid model calls go out per question — intent, then prose — and the webhook
# blocks on both before it replies. Unthrottled, one chat is therefore both a
# cost exposure and an availability one on an endpoint every tenant shares. The
# limiter already on the webhook is keyed by Telegram's own calling IP, so it
# caps all customers together and no single chat at all.
#
# In-process on purpose. This product deploys as a single replica, where a
# per-process bucket is a real ceiling; scale out and the right home for this is
# the Redis the scheduler already takes its job locks against, with the same
# shape as below.
ASK_MAX_PER_HOUR = 30
_ASK_WINDOW = timedelta(hours=1)

# chat_id -> the timestamps of its recent questions. Bounded by ASK_MAX_PER_HOUR
# entries per chat that has ever asked; a chat's own list is pruned whenever it
# asks again, so an active deployment stays flat.
_ask_calls: dict[str, list[datetime]] = {}


def _within_rate_limit(chat_id: str, now: datetime | None = None) -> bool:
    """Whether this chat may spend another two model calls right now.

    Records the attempt when it allows one, so callers must ask exactly once per
    question — a check that does not consume is not a limit.
    """
    now = now or datetime.now(timezone.utc)
    cutoff = now - _ASK_WINDOW
    recent = [stamp for stamp in _ask_calls.get(chat_id, ()) if stamp > cutoff]

    if len(recent) >= ASK_MAX_PER_HOUR:
        _ask_calls[chat_id] = recent
        return False

    recent.append(now)
    _ask_calls[chat_id] = recent
    return True


MAX_ANSWER_LINES = 6
MAX_LIST_ITEMS = 8
MAX_RANKED_ITEMS = 5

# Trips that are actually on the road. ``planned`` is excluded for the reason
# the morning briefing excludes it: a load nobody has picked up yet is not a
# truck the owner can see moving, and counting it inflates the one figure they
# can check by looking out of the window.
_ON_THE_ROAD = (TripStatus.loading, TripStatus.en_route, TripStatus.at_border)


# ── Language ─────────────────────────────────────────────────────────────

# Letters that exist in Uzbek Cyrillic and not in Russian. A fleet owner
# writing Uzbek in Cyrillic is a real customer, and answering them in Russian
# because their alphabet looked Russian is exactly the kind of small insult
# that makes a product feel foreign.
_UZBEK_CYRILLIC = set("ўқғҳЎҚҒҲ")
_CYRILLIC = re.compile(r"[Ѐ-ӿ]")
_LATIN = re.compile(r"[A-Za-z]")


def detect_language(text: str) -> str:
    """``"uz"`` or ``"ru"`` — the language the answer must be written in."""
    if any(ch in _UZBEK_CYRILLIC for ch in text):
        return "uz"
    return "ru" if len(_CYRILLIC.findall(text)) > len(_LATIN.findall(text)) else "uz"


# Every user-facing string, Uzbek and Russian side by side: a phrase added in
# one language and forgotten in the other is visible here instead of hiding at
# the bottom of a second dictionary.
_TEXT: dict[str, tuple[str, str]] = {
    "not_configured": (
        "🤖 Savolga javob berish hozircha yoqilmagan. "
        "Administrator AI kalitini sozlagach ishlaydi.",
        "🤖 Ответы на вопросы пока не включены. "
        "Заработают, когда администратор настроит AI-ключ.",
    ),
    "suspended": (
        "⏸ Hisobingiz vaqtincha faol emas. Administrator bilan bog'laning.",
        "⏸ Ваш аккаунт временно неактивен. Свяжитесь с администратором.",
    ),
    "refuse": (
        "Buni hozircha ayta olmayman.\n"
        "Men bilganlarim: yo'ldagi mashinalar, mashinaning joylashuvi, "
        "davlatlar bo'yicha xarajat, yoqilg'i sarfi, yo'qotishlar.",
        "Пока не могу это сказать.\n"
        "Я знаю: машины в рейсе, местоположение машины, расходы по странам, "
        "расход топлива, потери.",
    ),
    "rate_limited": (
        "Juda ko'p savol berildi. Bir ozdan keyin qayta urinib ko'ring.",
        "Слишком много вопросов подряд. Попробуйте чуть позже.",
    ),
    "error": (
        "Hozir javob bera olmadim. Birozdan keyin qayta yozing.",
        "Сейчас не смог ответить. Напишите чуть позже.",
    ),
    # Russian counts carry no unit word — "3 шт машин" is not how anyone speaks.
    "u_count": ("ta", ""),
    "u_liters": ("l", "л"),
    "u_money": ("so'm", "сум"),
    "u_hours": ("soat", "ч"),
    "u_days": ("kun", "дн."),
    "u_kmh": ("km/soat", "км/ч"),
    "road_count": ("🚚 Hozir yo'lda", "🚚 Сейчас в рейсе"),
    "truck_not_found": (
        "🚫 Bunday davlat raqamli mashina topilmadi",
        "🚫 Машина с таким госномером не найдена",
    ),
    "position_none": ("📍 Joylashuv ma'lumoti yo'q", "📍 Нет данных о местоположении"),
    "coords": ("Koordinata", "Координаты"),
    "speed": ("Tezlik", "Скорость"),
    "moment": ("Vaqt", "Время"),
    "address": ("Manzil", "Адрес"),
    "spend_title": ("💰 Davlatlar bo'yicha xarajat", "💰 Расходы по странам"),
    "truck": ("Mashina", "Машина"),
    "period": ("Davr", "Период"),
    "total": ("Jami", "Итого"),
    "spend_none": (
        "Bu davrda xarajat qayd etilmagan.",
        "За этот период расходов не зафиксировано.",
    ),
    "spend_no_rate": ("Kurs kiritilmagan, USD to'liq emas", "Курс не задан, USD неполный"),
    "fuel_title": ("⛽ Yoqilg'i sarfi", "⛽ Расход топлива"),
    "fuel_none": ("Bu davrda yoqilg'i quyilmagan.", "За этот период заправок не было."),
    "leak_title": ("🔎 Yo'qotishlar", "🔎 Потери"),
    "leak_waste": ("Yoqilg'i isrofi", "Перерасход топлива"),
    "leak_flagged": ("Belgilangan mashinalar", "Отмеченные машины"),
    "leak_stops": ("Ruxsatsiz to'xtashlar", "Стоянки вне точек"),
    "leak_idle": ("Bekor turish", "Простой"),
    "leak_active": ("Yo'ldagi reyslar", "Рейсы в пути"),
    "leak_delivered": ("Yetkazilgan reyslar", "Доставленные рейсы"),
}

_COUNTRY_LABEL: dict[str, tuple[str, str]] = {
    "uz": ("O'zbekiston", "Узбекистан"),
    "kz": ("Qozog'iston", "Казахстан"),
    "ru": ("Rossiya", "Россия"),
}

_STATUS_LABEL: dict[TripStatus, tuple[str, str]] = {
    TripStatus.loading: ("yuklanmoqda", "погрузка"),
    TripStatus.en_route: ("yo'lda", "в пути"),
    TripStatus.at_border: ("chegarada", "на границе"),
}


def _pick(lang: str, pair: tuple[str, str]) -> str:
    return pair[1] if lang == "ru" else pair[0]


def _say(lang: str, key: str) -> str:
    return _pick(lang, _TEXT.get(key, ("", "")))


def _cannot(lang: str, key: str) -> str:
    """A "no" that still leaves the owner somewhere to go."""
    return f"{_say(lang, key)}\n\n{_COMMAND_HINT}"


def _country(lang: str, code: str) -> str:
    return _pick(lang, _COUNTRY_LABEL.get(code, (code, code)))


# ── Figures ──────────────────────────────────────────────────────────────
#
# A capability states a number by building a :class:`Figure` and putting its
# ``text`` into a line. Nothing else ever writes a digit into a line, which is
# what makes "every number in the fact sheet is in ``figures``" true by
# construction rather than by review.


def _group(value: float) -> str:
    """Thousands separated by spaces, the way an Uzbek invoice is written."""
    return f"{int(value):,}".replace(",", " ")


def _figure(key: str, label: str, text: str, value: float) -> Figure:
    return Figure(key=key, label=label, text=text.strip(), value=value)


def _count(lang: str, key: str, label: str, value: float) -> Figure:
    whole = int(value)
    return _figure(key, label, f"{_group(whole)} {_say(lang, 'u_count')}", float(whole))


def _money(lang: str, key: str, label: str, value: float) -> Figure:
    # UZS across the board, matching every other money total in this product.
    rounded = round(float(value))
    return _figure(key, label, f"{_group(rounded)} {_say(lang, 'u_money')}", float(rounded))


def _liters(lang: str, key: str, label: str, value: float) -> Figure:
    rounded = round(float(value))
    return _figure(key, label, f"{_group(rounded)} {_say(lang, 'u_liters')}", float(rounded))


def _hours(lang: str, key: str, label: str, value: float) -> Figure:
    rounded = round(float(value), 1)
    return _figure(key, label, f"{rounded:.1f} {_say(lang, 'u_hours')}", rounded)


def _days(lang: str, key: str, label: str, value: int) -> Figure:
    return _figure(key, label, f"{value} {_say(lang, 'u_days')}", float(value))


def _amount(key: str, label: str, value: float, currency: str) -> Figure:
    """An amount in the currency it was actually spent in. Never summed with
    another currency — that is what the USD column exists for."""
    rounded = round(float(value))
    return _figure(key, label, f"{_group(rounded)} {currency}", float(rounded))


def _rank(index: int) -> Figure:
    """The ``3.`` in front of a ranked row.

    It is a number the owner can see, so the model is allowed to repeat it;
    leaving it out of the allow-list would reject every correctly numbered list.
    """
    return _figure(f"rank{index}", "", str(index), float(index))


def _labelled(figure: Figure) -> str:
    return f"{figure.label}: {figure.text}"


# ── Facts ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Facts:
    """One capability's answer: what to say, and what the model may repeat.

    ``lines`` is a complete answer on its own — it ships verbatim whenever the
    model is absent or fails verification. ``figures`` and ``literals`` are the
    two halves of the allow-list: measured numbers, and the strings that merely
    contain digits (plates, dates, coordinates, truck names).
    """

    lines: list[str]
    figures: list[Figure] = field(default_factory=list)
    literals: list[str] = field(default_factory=list)

    def sheet(self) -> str:
        return "\n".join(self.lines)


@dataclass(frozen=True)
class Ctx:
    """Everything a capability may use. ``org_id`` is not negotiable."""

    db: AsyncSession
    org_id: uuid.UUID
    lang: str
    args: dict[str, Any]


# ── Argument coercion ────────────────────────────────────────────────────
#
# The model's arguments are untrusted input like any other. Nothing below can
# widen a query beyond the asking organization; the worst a bad argument does
# is pick a different window.

_MONTH_RE = re.compile(r"^(\d{4})-(\d{1,2})$")


def _arg_plate(args: dict[str, Any]) -> str:
    raw = args.get("plate") or args.get("truck") or ""
    return str(raw).strip()[:20]


def _arg_days(args: dict[str, Any], *, default: int, maximum: int) -> int:
    try:
        days = int(args.get("days"))
    except (TypeError, ValueError):
        return default
    return max(1, min(days, maximum))


def _arg_month(args: dict[str, Any]) -> tuple[date, date] | None:
    """``"2026-08"`` → the first and last day of that month, else ``None``."""
    match = _MONTH_RE.match(str(args.get("month") or "").strip())
    if match is None:
        return None
    year, month = int(match.group(1)), int(match.group(2))
    if not 1 <= month <= 12 or not 2000 <= year <= 2100:
        return None
    start = date(year, month, 1)
    end = date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)
    return start, end


def _normalise_plate(raw: str) -> str:
    return re.sub(r"[^0-9A-Z]", "", raw.upper())


def _fmt_date(value: date) -> str:
    return value.strftime("%d.%m.%Y")


async def _find_truck(db: AsyncSession, org_id: uuid.UUID, plate: str) -> Truck | None:
    """The org's truck for a plate typed by hand, or ``None``.

    Scoped to ``org_id`` before anything else: ``plate_number`` is unique across
    the whole table, so the unscoped version of this function answers questions
    about other companies' trucks.

    Owners type plates from memory, with and without spaces, so the comparison
    ignores punctuation and a unique partial match is accepted. Two partial
    matches are not — an ambiguous guess about which truck is worse than asking
    again.
    """
    wanted = _normalise_plate(plate)
    if not wanted:
        return None
    trucks = list(
        (await db.execute(select(Truck).where(Truck.org_id == org_id))).scalars().all()
    )
    for truck in trucks:
        if _normalise_plate(truck.plate_number) == wanted:
            return truck
    partial = [t for t in trucks if wanted in _normalise_plate(t.plate_number)]
    return partial[0] if len(partial) == 1 else None


def _truck_missing(ctx: Ctx, plate: str) -> Facts:
    return Facts(lines=[f"{_say(ctx.lang, 'truck_not_found')}: {plate}"], literals=[plate])


# ── Capabilities ─────────────────────────────────────────────────────────


async def cap_active_trips(ctx: Ctx) -> Facts:
    """Which trucks are on the road right now."""
    rows = (
        await ctx.db.execute(
            select(
                Trip.reference,
                Trip.status,
                Trip.origin_name,
                Trip.destination_name,
                Truck.plate_number,
                Driver.name,
            )
            .select_from(Trip)
            .outerjoin(Truck, Truck.id == Trip.truck_id)
            .outerjoin(Driver, Driver.id == Trip.driver_id)
            .where(Trip.org_id == ctx.org_id, Trip.status.in_(_ON_THE_ROAD))
            .order_by(Trip.started_at.desc().nulls_last())
        )
    ).all()

    count = _count(ctx.lang, "on_road", _say(ctx.lang, "road_count"), len(rows))
    lines = [_labelled(count)]
    figures = [count]
    literals: list[str] = []

    for index, (reference, status, origin, destination, plate, driver) in enumerate(
        rows[:MAX_LIST_ITEMS], start=1
    ):
        rank = _rank(index)
        who = plate or reference
        route = " → ".join(part for part in (origin, destination) if part)
        status_label = _pick(ctx.lang, _STATUS_LABEL.get(status, ("", "")))
        parts = [part for part in (route, status_label, driver) if part]
        detail = " — " + " · ".join(parts) if parts else ""
        lines.append(f"{rank.text}. {who}{detail}")
        figures.append(rank)
        literals.extend(str(part) for part in (who, origin, destination, driver) if part)

    return Facts(lines=lines, figures=figures, literals=literals)


async def cap_truck_position(ctx: Ctx) -> Facts:
    """Where one truck was last seen."""
    plate = _arg_plate(ctx.args)
    truck = await _find_truck(ctx.db, ctx.org_id, plate)
    if truck is None:
        return _truck_missing(ctx, plate)

    location = (
        await ctx.db.execute(select(TruckLocation).where(TruckLocation.truck_id == truck.id))
    ).scalar_one_or_none()

    head = f"📍 {truck.plate_number} · {truck.name}"
    literals = [truck.plate_number, truck.name]
    if location is None:
        return Facts(lines=[head, _say(ctx.lang, "position_none")], literals=literals)

    # Coordinates and the timestamp are literals, not figures: they are an
    # address, not a measurement, and nothing in the answer may do arithmetic
    # on them.
    lat = f"{float(location.latitude):.5f}"
    lng = f"{float(location.longitude):.5f}"
    seen = location.recorded_at.astimezone(report_tz())
    day, clock = _fmt_date(seen.date()), seen.strftime("%H:%M")
    kmh = round(float(location.speed or 0))
    speed = _figure("speed", _say(ctx.lang, "speed"), f"{kmh} {_say(ctx.lang, 'u_kmh')}", float(kmh))

    lines = [
        head,
        f"{_say(ctx.lang, 'coords')}: {lat}, {lng}",
        _labelled(speed),
        f"{_say(ctx.lang, 'moment')}: {day} {clock}",
    ]
    literals.extend([lat, lng, day, clock])
    if location.address:
        lines.append(f"{_say(ctx.lang, 'address')}: {location.address}")
        literals.append(location.address)
    return Facts(lines=lines, figures=[speed], literals=literals)


async def cap_country_spending(ctx: Ctx) -> Facts:
    """What a truck (or the whole fleet) spent in each country over a period."""
    plate = _arg_plate(ctx.args)
    truck: Truck | None = None
    if plate:
        truck = await _find_truck(ctx.db, ctx.org_id, plate)
        if truck is None:
            return _truck_missing(ctx, plate)

    month = _arg_month(ctx.args)
    if month is not None:
        start, end = month
    else:
        end = datetime.now(report_tz()).date()
        start = end - timedelta(days=_arg_days(ctx.args, default=30, maximum=365) - 1)

    report = await build_country_expense_report(
        ctx.db, ctx.org_id, start=start, end=end, truck_id=truck.id if truck else None
    )

    lines = [_say(ctx.lang, "spend_title")]
    literals = [_fmt_date(start), _fmt_date(end)]
    if truck is not None:
        lines.append(f"{_say(ctx.lang, 'truck')}: {truck.plate_number}")
        literals.append(truck.plate_number)
    lines.append(f"{_say(ctx.lang, 'period')}: {_fmt_date(start)} – {_fmt_date(end)}")

    figures: list[Figure] = []
    blocks = [block for block in report.countries if not block.is_empty]
    if not blocks:
        lines.append(_say(ctx.lang, "spend_none"))
        return Facts(lines=lines, figures=figures, literals=literals)

    for block in blocks:
        label = _country(ctx.lang, block.country)
        native = _amount(f"{block.country}_native", label, block.total, block.currency)
        figures.append(native)
        if block.total_usd is None:
            # No rate anywhere for this country. The native number still stands;
            # inventing the USD one is what this report exists to avoid.
            lines.append(f"{_labelled(native)} ({_say(ctx.lang, 'spend_no_rate')})")
            continue
        usd = _amount(f"{block.country}_usd", label, block.total_usd, "USD")
        figures.append(usd)
        lines.append(f"{_labelled(native)} ≈ {usd.text}")

    if report.total_usd is not None:
        total = _amount("total_usd", _say(ctx.lang, "total"), report.total_usd, "USD")
        figures.append(total)
        lines.append(_labelled(total))
    if report.usd_partial:
        missing = ", ".join(
            _country(ctx.lang, code) for code in report.countries_missing_rate
        )
        lines.append(f"{_say(ctx.lang, 'spend_no_rate')}: {missing}")

    return Facts(lines=lines, figures=figures, literals=literals)


async def cap_fuel_ranking(ctx: Ctx) -> Facts:
    """Which trucks burned the most fuel, and what it cost."""
    days = _arg_days(ctx.args, default=30, maximum=180)
    start = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (await gather_fuel(ctx.db, start, ctx.org_id))["by_truck"]
    rows.sort(key=lambda row: row["liters"], reverse=True)

    window = _days(ctx.lang, "window", _say(ctx.lang, "period"), days)
    lines = [f"{_say(ctx.lang, 'fuel_title')} · {window.text}"]
    figures = [window]
    literals: list[str] = []

    if not rows:
        lines.append(_say(ctx.lang, "fuel_none"))
        return Facts(lines=lines, figures=figures, literals=literals)

    for index, row in enumerate(rows[:MAX_RANKED_ITEMS], start=1):
        rank = _rank(index)
        litres = _liters(ctx.lang, f"l{index}", "", row["liters"])
        cost = _money(ctx.lang, f"c{index}", "", row["total_cost"])
        lines.append(f"{rank.text}. {row['truck']}: {litres.text} · {cost.text}")
        figures.extend([rank, litres, cost])
        # The label is "Volvo (01A123BC)" — a name carrying a plate's digits.
        literals.append(str(row["truck"]))

    return Facts(lines=lines, figures=figures, literals=literals)


async def cap_leakage(ctx: Ctx) -> Facts:
    """Where money is leaking: fuel waste, unauthorized stops, idle time."""
    # Capped at 30 days: this scans GPS history, and a question typed on a whim
    # should not be able to start a year-long scan inside a webhook request.
    days = _arg_days(ctx.args, default=7, maximum=30)
    summary = await leakage_summary(ctx.db, days, ctx.org_id)

    # ``window_days`` rather than ``days``: analytics clamps the request to the
    # period raw GPS history is actually kept, and the answer must state the
    # window it really measured.
    window = _days(ctx.lang, "window", _say(ctx.lang, "period"), int(summary["window_days"]))
    figures = [
        window,
        _money(ctx.lang, "waste", _say(ctx.lang, "leak_waste"), summary["estimated_fuel_waste_cost"]),
        _count(ctx.lang, "flagged", _say(ctx.lang, "leak_flagged"), summary["flagged_trucks"]),
        _count(ctx.lang, "stops", _say(ctx.lang, "leak_stops"), summary["unauthorized_stop_count"]),
        _hours(ctx.lang, "idle", _say(ctx.lang, "leak_idle"), summary["total_idle_hours"]),
        _count(ctx.lang, "active", _say(ctx.lang, "leak_active"), summary["active_trips"]),
        _count(ctx.lang, "delivered", _say(ctx.lang, "leak_delivered"), summary["delivered_trips"]),
    ]
    lines = [f"{_say(ctx.lang, 'leak_title')} · {window.text}"]
    lines.extend(_labelled(figure) for figure in figures[1:])
    return Facts(lines=lines, figures=figures)


# The whole vocabulary. A name the model returns that is not a key here is a
# refusal, not an approximation.
CAPABILITIES: dict[str, Callable[[Ctx], Awaitable[Facts]]] = {
    "active_trips": cap_active_trips,
    "truck_position": cap_truck_position,
    "country_spending": cap_country_spending,
    "fuel_ranking": cap_fuel_ranking,
    "leakage": cap_leakage,
}

# What the model is allowed to want. Written for the model, in English, and
# deliberately the only description of the system it ever sees.
_CATALOGUE = """\
- active_trips() — which trucks are on the road right now, with route, status and driver
- truck_position(plate) — last known position, speed and time for one truck
- country_spending(plate?, month?, days?) — money spent in Uzbekistan / Kazakhstan / Russia, \
taken from the drivers' trip expense forms, in each country's own currency and in USD
- fuel_ranking(days?) — which trucks burned the most fuel, litres and cost
- leakage(days?) — losses: fuel waste against the fleet baseline, unauthorized stops, idle hours\
"""


# ── The model's two jobs ─────────────────────────────────────────────────


def build_intent_prompt(question: str, today: date) -> tuple[str, str]:
    """Pick a capability. The model answers with JSON and nothing else."""
    system = (
        "You route one question from the owner of an Uzbek trucking company to exactly one "
        "read-only capability of their fleet system. You never answer the question yourself "
        "and you never see any data.\n"
        f"Today is {today.isoformat()} in Asia/Tashkent.\n"
        f"Capabilities:\n{_CATALOGUE}\n"
        'Reply with one JSON object and nothing else: {"capability": "<name>", '
        '"arguments": {...}}.\n'
        'Reply {"capability": null} whenever the question needs anything not listed above. '
        "A refusal is correct; a capability that nearly fits is not.\n"
        'Arguments: omit any the question did not give you. "plate" is the licence plate '
        'copied from the question. "month" is YYYY-MM. "days" is a whole number of days '
        "back from today."
    )
    return system, question


def build_answer_prompt(question: str, facts: Facts, lang: str) -> tuple[str, str]:
    """Phrase the fact sheet. Every rule here exists to stop an invented number."""
    system = (
        f"You answer the owner of an Uzbek trucking company in their Telegram chat. Write "
        f"entirely in {LANGUAGE_NAMES.get(lang, 'Uzbek')}, in short plain sentences.\n"
        "Rules that override everything else:\n"
        "- Answer only from the facts below. They are everything the system knows.\n"
        "- Use ONLY the numbers in the facts. Copy each one exactly as written, digit for "
        "digit and space for space, together with its unit.\n"
        "- Never calculate, round, convert, compare or estimate a number, and never write a "
        "number that is not in the facts.\n"
        "- If the facts do not answer the question, say so in one sentence.\n"
        "- At most four lines. No markdown, no headings, no bullet characters."
    )
    # Labelled in English, like the rules above it: an Uzbek framing word here
    # pulls the answer towards Uzbek even when the question was Russian.
    user = f"Question: {question}\n\nFacts:\n{facts.sheet()}"
    return system, user


async def _ask_model(system: str, user: str) -> str | None:
    """One completion, or ``None`` if the provider was slow, angry or absent."""
    try:
        return await asyncio.wait_for(call_chat_completion(system, user), timeout=AI_TIMEOUT_S)
    except Exception:  # noqa: BLE001 — an outage is an answer we can phrase, not a crash.
        logger.warning("ask_ai_call_failed", exc_info=True)
        return None


_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def parse_intent(raw: str) -> tuple[str | None, dict[str, Any]]:
    """``(capability name, arguments)`` from the router's reply.

    Tolerant about packaging — models fence JSON in ``` and add a sentence of
    commentary — and strict about content: anything that does not yield a
    capability name comes back as ``None``, which the caller turns into a
    refusal rather than a guess.
    """
    match = _JSON_RE.search(raw or "")
    if match is None:
        return None, {}
    try:
        payload = json.loads(match.group(0))
    except (TypeError, ValueError):
        return None, {}
    if not isinstance(payload, dict):
        return None, {}
    name = payload.get("capability")
    args = payload.get("arguments")
    if not isinstance(name, str) or not name.strip():
        return None, {}
    return name.strip().lower(), args if isinstance(args, dict) else {}


def _strip_literals(text: str, literals: list[str]) -> str:
    """Remove the strings that carry digits without being measurements.

    "01A123BC" reads to a number scanner as 01 and 123, so an otherwise perfect
    answer that names the truck would be thrown away. Longest first, so
    removing "01.08.2026" cannot leave a stray "2026" behind.
    """
    cleaned = text
    for literal in sorted({item for item in literals if item}, key=len, reverse=True):
        cleaned = re.sub(re.escape(literal), " ", cleaned, flags=re.IGNORECASE)
    return cleaned


def invented_numbers(text: str, facts: Facts) -> list[str]:
    """Every number in ``text`` that the fact sheet did not contain.

    The gate the whole feature rests on, and deliberately unforgiving: a model
    that helpfully totals two of our figures has produced a number nobody
    measured, and an answer mixing measured and derived numbers is worse than
    the plain fact sheet.
    """
    return unverified_numbers(_strip_literals(text, facts.literals), facts.figures)


async def compose_answer(question: str, facts: Facts, lang: str) -> str | None:
    """The model's phrasing of ``facts``, or ``None`` to use the sheet itself."""
    raw = await _ask_model(*build_answer_prompt(question, facts, lang))
    if raw is None:
        return None
    lines = [line.strip() for line in raw.splitlines() if line.strip()][:MAX_ANSWER_LINES]
    if not lines:
        return None
    answer = "\n".join(lines)
    invented = invented_numbers(answer, facts)
    if invented:
        logger.warning("ask_ai_invented_numbers", numbers=invented[:5])
        return None
    return answer


# ── Entry point ──────────────────────────────────────────────────────────


def _primary(accounts: list[TelegramAccount]) -> TelegramAccount | None:
    """The company this chat's question is about.

    One chat, one set of books. A person who owns two companies from the same
    chat gets the oldest live link's company and sees its name above the answer;
    merging the two would produce totals that belong to neither business.

    A ``/stop``ped link still answers. ``/stop`` silences the alerts this bot
    pushes at the owner — a question they have just typed is not a push.
    """
    if not accounts:
        return None
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    return sorted(
        accounts, key=lambda a: (not a.is_active, a.created_at or epoch, str(a.id))
    )[0]


async def _answer(db: AsyncSession, org_id: uuid.UUID, question: str, lang: str) -> str:
    """Route, run, phrase. Plain text — the caller escapes it."""
    raw = await _ask_model(*build_intent_prompt(question, datetime.now(report_tz()).date()))
    if raw is None:
        return _say(lang, "error")

    name, args = parse_intent(raw)
    capability = CAPABILITIES.get(name or "")
    if capability is None:
        logger.info("ask_out_of_scope", org_id=str(org_id), capability=name)
        return _cannot(lang, "refuse")

    facts = await capability(Ctx(db=db, org_id=org_id, lang=lang, args=args))
    return await compose_answer(question, facts, lang) or facts.sheet()


async def answer_question(
    db: AsyncSession, accounts: list[TelegramAccount], text: str
) -> str | None:
    """Answer whatever an owner typed, or ``None`` when there is nothing to answer.

    Registered as the free-text fallback in :mod:`~app.services.owner_alerts.commands`,
    so it sees only messages that are not slash commands. Never raises: the
    webhook swallows exceptions, and a crash here reads to the owner as the bot
    ignoring them.
    """
    question = (text or "").strip()[:MAX_QUESTION_CHARS]
    if not question:
        return None

    account = _primary(accounts)
    if account is None:
        return None

    lang = detect_language(question)
    try:
        org = (
            await db.execute(select(Organization).where(Organization.id == account.org_id))
        ).scalar_one_or_none()
        # A suspended customer is locked out of the panel; the bot is not a way
        # back in to the same numbers.
        if org is None or not org.is_active:
            return _say(lang, "suspended")
        if not settings.ai_api_key:
            return _cannot(lang, "not_configured")
        # Keyed on the chat, not the org: the chat is what sends messages, and
        # one noisy phone must not spend a company's whole hourly budget.
        if not _within_rate_limit(account.chat_id or str(account.id)):
            logger.info("ask_rate_limited", org_id=str(account.org_id))
            return _say(lang, "rate_limited")
        answer = await _answer(db, account.org_id, question, lang)
    except Exception:  # noqa: BLE001
        logger.exception("ask_failed", org_id=str(account.org_id))
        try:
            await db.rollback()  # leave the session usable for the next update
        except Exception:  # noqa: BLE001
            logger.exception("ask_rollback_failed")
        return _say(lang, "error")

    # Escaped once, here, at the boundary: the fact sheet and the model's prose
    # are both plain text until this line, so a truck called "Neft & Gaz"
    # survives either path intact.
    body = "\n".join(html.escape(line, quote=False) for line in answer.splitlines())
    if len({a.org_id for a in accounts}) > 1:
        return f"<b>{html.escape(org.name, quote=False)}</b>\n{body}"
    return body


register_fallback(answer_question)
