"""Turn a photographed receipt into a *suggested* trip-expense line.

Today a driver standing at a truck stop in Aqtöbe hand-types every figure of
the "yo'l varaqasi" into a phone, and the country-expense report — the number an
owner uses to decide whether a run made money — rests on those keystrokes. A
camera removes the typing. It does not remove the judgement.

**Nothing in this module is ever written to the database.** :func:`scan_receipt`
reads an image and returns a reading; the driver sees it, corrects it, and the
existing ``PUT /api/me/trips/{trip_id}/report`` path stores what they confirmed.
That separation is the whole difference between a helpful feature and a system
that quietly fabricates expense records: a model that reads 12 500 as 125 000
costs a driver ten seconds while the number is a suggestion, and costs a fleet
its books the moment it becomes a fact.

Three consequences shape the code below.

**The model may only answer in the vocabulary the database accepts.** The prompt
is generated from :class:`TripReportCountry` and
:class:`TripReportExpenseCategory`, so a new enum member reaches the model
automatically, and a value outside them is rejected instead of coerced. A
plausible-looking ``food_and_drink`` is a reading nobody can store; failing at
this boundary is the only place it can be noticed.

**Every number is clamped before it is believed.** The amount is parsed from
whatever shape the model chose (``"12 500,00"`` is as likely as ``12500.0``),
forced positive, and held inside the ``Numeric(12, 2)`` the column can hold.
Confidence is squeezed into 0..1 — including the model that answers ``85``
meaning 85%, because rounding that up to "certain" is the one direction that
must never happen.

**Confidence is part of the answer, not an afterthought.** It is what lets the
client show a shaky reading differently from a crisp one, so it is also lowered
here when the reading contradicts itself: a currency that does not belong to the
country the model picked means the driver is about to accept a number in the
wrong unit, and the country table has no currency column to catch it later.
"""
from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Optional

import httpx

from app.core.config import settings
from app.core.logging import logger
from app.models.enums import TripReportCountry, TripReportExpenseCategory

# A phone photo at the quality the driver app uploads is ~1-2 MB. The ceiling is
# deliberately well above that and well below anything that would make a vision
# request expensive: the image is base64-encoded into the prompt, so bytes here
# are tokens upstream.
MAX_IMAGE_BYTES = 8 * 1024 * 1024

# Only formats a vision model can actually decode. HEIC/HEIF are missing on
# purpose: an iPhone original would upload happily and then fail deep inside the
# provider, and a 502 three seconds later teaches the driver nothing. A 415 at
# the door tells them to retake the photo.
ALLOWED_CONTENT_TYPES: frozenset[str] = frozenset(
    {"image/jpeg", "image/jpg", "image/png", "image/webp"}
)

# Providers are pickier about the data URI than about the upload header.
_DATA_URI_TYPE = {"image/jpg": "image/jpeg"}

# The four currencies the trip report accounts in (see ``TripReportTotals``).
CURRENCIES: tuple[str, ...] = ("usd", "rub", "kzt", "uzs")

# Which currency each country's expense table is denominated in. Used only to
# spot a self-contradicting reading, never to rewrite one.
_NATIVE_CURRENCY: dict[TripReportCountry, str] = {
    TripReportCountry.kz: "kzt",
    TripReportCountry.ru: "rub",
    TripReportCountry.uz: "uzs",
}

# ``TripCountryExpenseLine.amount`` is Numeric(12, 2).
MAX_AMOUNT = Decimal("9999999999.99")

# What the client shows as "check this one". A reading whose currency does not
# match its country is pinned below it — see the module docstring.
LOW_CONFIDENCE = 0.4

# The model answered but said nothing about how sure it was. Neither 0 (which
# reads as "this is wrong") nor 1 (which reads as "type nothing") is honest.
DEFAULT_CONFIDENCE = 0.5

VENDOR_MAX_LEN = 120

# Long enough for a slow provider to finish a vision call over a truck-stop
# connection, short enough that the driver gets an answer or an error rather
# than a spinner they have to guess about.
SCAN_TIMEOUT_S = 45.0


class ReceiptScanError(Exception):
    """Base for every failure the scan endpoint turns into an HTTP status."""


class ReceiptScanNotConfigured(ReceiptScanError):
    """No ``AI_API_KEY`` on this deployment — the feature is off, not broken."""


class ReceiptUnreadable(ReceiptScanError):
    """The model answered, but not with something storable.

    Covers both "this photo is not a receipt" and "the model invented a category
    that does not exist". Both are the driver's cue to type the line by hand,
    which is exactly what they do today, so neither is an error worth alarming
    anyone about.
    """


class ReceiptScanUnavailable(ReceiptScanError):
    """The upstream provider failed, timed out, or answered with nonsense."""


@dataclass(frozen=True)
class ReceiptReading:
    """One suggested expense line. Never persisted by this module."""

    country: TripReportCountry
    category: TripReportExpenseCategory
    amount: Decimal
    currency: str
    vendor: Optional[str]
    confidence: float


# ── Prompt ───────────────────────────────────────────────────────────────

# A gloss per category so the model can map what is actually printed on a
# Kazakh or Russian receipt onto our vocabulary. Missing entries are fine: the
# prompt falls back to the bare enum value, so adding a category never silently
# drops it from the list the model is allowed to choose from.
_CATEGORY_HINTS: dict[str, str] = {
    "platon": "road toll / Платон / Платон-KZ",
    "food": "a meal, cafe, restaurant",
    "traffic_police": "traffic police fine paid on the spot / ГАИ / ДПС",
    "adblue": "AdBlue / мочевина",
    "fine": "an official fine or penalty notice / штраф",
    "spare_parts": "parts bought for the truck / запчасть",
    "repair": "labour for a repair / ремонт / СТО",
    "refund": "money handed back to the driver / возврат",
    "parking": "truck parking / стоянка / парковка",
    "phone": "phone credit, SIM, mobile internet",
    "transport": "the driver's own transport (bus, train, ticket)",
    "shower": "shower / душ",
    "groceries": "food bought in a shop to cook or carry / продукты",
    "parking_paperwork": "parking paperwork at the terminal / оформление стоянка",
    "taxi": "taxi",
    "carwash": "truck wash / мойка",
}


def _enum_menu() -> str:
    return "\n".join(
        f"  - {member.value}: {_CATEGORY_HINTS.get(member.value, member.value)}"
        for member in TripReportExpenseCategory
    )


def build_prompt() -> tuple[str, str]:
    """The system/user pair sent with the photo.

    Built from the enums rather than written out, so the set of answers the model
    is offered and the set the database accepts cannot drift apart.
    """
    countries = ", ".join(member.value for member in TripReportCountry)
    system = (
        "You read photographs of paper receipts collected by long-haul truck "
        "drivers on the Uzbekistan-Kazakhstan-Russia corridor. Receipts are "
        "printed in Uzbek, Kazakh, Russian or English.\n\n"
        "Reply with one JSON object and nothing else:\n"
        '{"country": ..., "category": ..., "amount": ..., "currency": ..., '
        '"vendor": ..., "confidence": ...}\n\n'
        f"country must be exactly one of: {countries}\n"
        f"category must be exactly one of:\n{_enum_menu()}\n"
        f"currency must be exactly one of: {', '.join(CURRENCIES)}\n"
        "amount is the final total actually paid, as a plain number.\n"
        "vendor is the seller's name as printed, or null.\n"
        "confidence is a number from 0 to 1 for the reading as a whole.\n\n"
        "Never invent a value and never coin a country or category outside the "
        "lists above. If the photo is not a readable receipt, reply with "
        '{"confidence": 0} and null for everything else. Read the country from '
        "the language, currency and address printed on the receipt."
    )
    user = "Read this receipt."
    return system, user


# ── Parsing the answer ───────────────────────────────────────────────────

_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)
# Everything that is not part of a number: currency signs, letters, спасибо.
_NON_NUMERIC_RE = re.compile(r"[^0-9.,\-]")


def extract_json(answer: str) -> dict[str, Any]:
    """Pull the JSON object out of whatever the model wrapped it in.

    Models fence their JSON, or preface it with a sentence, often enough that
    treating the raw string as JSON would fail on answers that are perfectly
    good. Anything with no object in it at all is a provider problem, not a
    driver problem, hence :class:`ReceiptScanUnavailable`.
    """
    match = _JSON_OBJECT_RE.search(answer or "")
    if not match:
        raise ReceiptScanUnavailable("The reading service returned no JSON")
    try:
        payload = json.loads(match.group(0))
    except ValueError as exc:
        raise ReceiptScanUnavailable("The reading service returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise ReceiptScanUnavailable("The reading service returned invalid JSON")
    return payload


def _to_amount(raw: Any) -> Optional[Decimal]:
    """Parse a total out of any shape the model chose to write it in.

    ``12500``, ``12500.0``, ``"12 500,00"``, ``"12.500"`` and ``"KZT 12500"`` all
    reach us in practice. The separator rule is positional rather than
    locale-based: the rightmost of ``.`` and ``,`` is the decimal point, and a
    lone separator followed by three digits is a thousands mark. That is what a
    human reading the paper would conclude, which is the only standard both a
    Kazakh and a Russian receipt share.
    """
    if isinstance(raw, bool) or raw is None:
        return None
    if isinstance(raw, (int, float, Decimal)):
        try:
            value = Decimal(str(raw))
        except InvalidOperation:
            return None
    elif isinstance(raw, str):
        cleaned = _NON_NUMERIC_RE.sub("", raw)
        if not cleaned:
            return None
        last_dot, last_comma = cleaned.rfind("."), cleaned.rfind(",")
        decimal_pos = max(last_dot, last_comma)
        if decimal_pos == -1:
            normalized = cleaned
        else:
            head, tail = cleaned[:decimal_pos], cleaned[decimal_pos + 1 :]
            head = head.replace(".", "").replace(",", "")
            # Exactly three trailing digits and no other separator is a
            # thousands mark ("12.500"), not two-and-a-half tenge.
            normalized = head + tail if len(tail) == 3 else f"{head}.{tail}"
        try:
            value = Decimal(normalized)
        except InvalidOperation:
            return None
    else:
        return None

    if not value.is_finite() or value <= 0 or value > MAX_AMOUNT:
        return None
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _to_confidence(raw: Any) -> float:
    """Squeeze whatever the model said about its own certainty into 0..1.

    A model that answers ``85`` means 85%, and reading that as "clamp to 1.0"
    would dress a coin-flip up as a certainty — the one rounding direction that
    can cost a driver money. Anything unparsable becomes
    :data:`DEFAULT_CONFIDENCE`, because "I don't know how sure it was" is not
    "it was sure".
    """
    if isinstance(raw, bool) or raw is None:
        return DEFAULT_CONFIDENCE
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return DEFAULT_CONFIDENCE
    if value != value or value in (float("inf"), float("-inf")):  # NaN / inf
        return DEFAULT_CONFIDENCE
    if 1.0 < value <= 100.0:
        value /= 100.0
    return min(1.0, max(0.0, value))


def _to_vendor(raw: Any) -> Optional[str]:
    if not isinstance(raw, str):
        return None
    vendor = " ".join(raw.split())[:VENDOR_MAX_LEN].strip()
    return vendor or None


def _to_country(raw: Any) -> Optional[TripReportCountry]:
    if not isinstance(raw, str):
        return None
    value = raw.strip().lower()
    # "rf" is the only alias worth honouring: the paper form itself labels the
    # Russian fuel column RF, so that abbreviation is all over this product's
    # own vocabulary and a model picks it up. Every other near-miss is a real
    # miss and must fail.
    if value == "rf":
        value = TripReportCountry.ru.value
    try:
        return TripReportCountry(value)
    except ValueError:
        return None


def _to_category(raw: Any) -> Optional[TripReportExpenseCategory]:
    if not isinstance(raw, str):
        return None
    try:
        return TripReportExpenseCategory(raw.strip().lower())
    except ValueError:
        return None


def parse_reading(payload: dict[str, Any]) -> ReceiptReading:
    """Validate and clamp a model answer into a storable suggestion.

    Raises :class:`ReceiptUnreadable` for anything the driver would have to fix
    anyway. It is a 422 rather than a 500 on purpose: an invented category is a
    routine outcome of asking a model for one, not a server fault, and the app's
    answer to it — "type this line yourself" — is the same either way.
    """
    country = _to_country(payload.get("country"))
    if country is None:
        raise ReceiptUnreadable("Could not tell which country this receipt is from")

    category = _to_category(payload.get("category"))
    if category is None:
        raise ReceiptUnreadable("Could not match this receipt to an expense category")

    amount = _to_amount(payload.get("amount"))
    if amount is None:
        raise ReceiptUnreadable("Could not read a total from this photo")

    currency = payload.get("currency")
    currency = currency.strip().lower() if isinstance(currency, str) else ""
    if currency not in CURRENCIES:
        # A total in an unknown currency is a number with no unit, and the
        # country table has no currency column to record the doubt in.
        raise ReceiptUnreadable("Could not read the currency on this receipt")

    confidence = _to_confidence(payload.get("confidence"))
    if currency != _NATIVE_CURRENCY[country]:
        confidence = min(confidence, LOW_CONFIDENCE)

    return ReceiptReading(
        country=country,
        category=category,
        amount=amount,
        currency=currency,
        vendor=_to_vendor(payload.get("vendor")),
        confidence=confidence,
    )


# ── The vision call ──────────────────────────────────────────────────────


def _data_uri(image: bytes, content_type: str) -> str:
    media_type = _DATA_URI_TYPE.get(content_type, content_type)
    return f"data:{media_type};base64,{base64.b64encode(image).decode('ascii')}"


async def call_vision(image: bytes, content_type: str) -> str:
    """Ask the configured OpenAI-compatible endpoint to read the photo.

    Returns the raw assistant text. Every transport-level failure becomes
    :class:`ReceiptScanUnavailable` so the router never has to decide what an
    ``httpx`` exception means, and the upstream detail never reaches the driver.
    """
    if not settings.ai_api_key:
        raise ReceiptScanNotConfigured("Receipt scanning is not configured on this server")

    system, user = build_prompt()
    body = {
        "model": settings.ai_model,
        "messages": [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user},
                    {"type": "image_url", "image_url": {"url": _data_uri(image, content_type)}},
                ],
            },
        ],
        # Reading a printed total is transcription, not writing: any creativity
        # here is a wrong number.
        "temperature": 0,
        "max_tokens": 300,
        "response_format": {"type": "json_object"},
    }
    url = f"{settings.ai_base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.ai_api_key}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=SCAN_TIMEOUT_S) as client:
            res = await client.post(url, headers=headers, json=body)
            res.raise_for_status()
            data = res.json()
        return data["choices"][0]["message"]["content"] or ""
    except Exception as exc:  # noqa: BLE001 — one provider, many failure shapes.
        logger.warning("receipt_scan_call_failed", error=str(exc))
        raise ReceiptScanUnavailable("The receipt reading service is unavailable") from exc


async def scan_receipt(image: bytes, content_type: str) -> ReceiptReading:
    """Read one receipt photo into a suggested expense line.

    Writes nothing. The caller returns this to the driver, who confirms or
    corrects it before the normal report-save path stores anything.
    """
    answer = await call_vision(image, content_type)
    return parse_reading(extract_json(answer))
