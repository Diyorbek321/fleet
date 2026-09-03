"""Receipt scanning — a camera replacing the keystrokes the report rests on.

The risk this suite exists for is not "the model misreads a photo"; it will, and
the driver fixes it. The risk is a misreading that *looks* like a fact: a
category nobody can store slipping through as a 500, a total in the wrong
currency arriving with full confidence, or a scan quietly leaving a row behind.
So the tests fall into three groups — what the model is allowed to say, what
happens to the numbers it says, and the proof that a scan writes nothing.
"""
from __future__ import annotations

from decimal import Decimal

import httpx
import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import func, select

from app.core.config import settings
from app.main import app
from app.models.driver_app import DriverExpense
from app.models.enums import TripReportCountry, TripReportExpenseCategory
from app.models.trip_reports import TripCountryExpenseLine, TripExpenseReport
from app.routers.me._common import PREFIX
from app.services import receipts

SCAN_PATH = f"{PREFIX}/receipts/scan"

# Not a real JPEG — nothing in the path decodes the bytes, they are base64'd
# straight into the prompt — but it carries the right magic number so a future
# sniffing check would still see an image.
JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"receipt" * 32


def _upload(data: bytes = JPEG_BYTES, content_type: str = "image/jpeg") -> dict:
    return {"file": ("receipt.jpg", data, content_type)}


def _answer(**overrides) -> dict:
    """A well-formed model answer, so each test can spoil exactly one field."""
    return {
        "country": "kz",
        "category": "food",
        "amount": 4500,
        "currency": "kzt",
        "vendor": "Kafe Dastarkhan",
        "confidence": 0.9,
        **overrides,
    }


def test_the_driver_api_actually_mounts_the_scan_endpoint():
    """``app/routers/me/__init__.py`` must include this sub-router.

    It did not, for as long as a fixture here mounted the router itself so the
    rest of the file could run. That made every other test below pass against a
    route the real app never served: the driver's scan button got a 404 and
    nothing in the suite noticed. This is the one assertion that reads the
    assembled app rather than the router object, so the wiring cannot go missing
    again without a red test.
    """
    assert SCAN_PATH in {getattr(route, "path", None) for route in app.routes}


@pytest_asyncio.fixture
async def driver_headers(driver_login) -> dict[str, str]:
    return driver_login["headers"]


@pytest.fixture
def model_says(monkeypatch):
    """Put words in the model's mouth.

    Patches the network call, not :func:`~app.services.receipts.scan_receipt`,
    so every test still runs the real JSON extraction, validation and clamping —
    which is where the behaviour under test actually lives.
    """

    def _set(raw_answer: str):
        async def _fake_call(image: bytes, content_type: str) -> str:
            return raw_answer

        monkeypatch.setattr(receipts, "call_vision", _fake_call)

    return _set


# ── The vocabulary the model is allowed to answer in ─────────────────────


class TestPrompt:
    def test_every_storable_category_is_offered_to_the_model(self):
        """The menu is generated from the enum, so the two cannot drift.

        A category added to the database but missing from the prompt is a
        category the model will never pick — the column exists, the feature
        silently never fills it, and nobody finds out from a test.
        """
        system, _ = receipts.build_prompt()
        for member in TripReportExpenseCategory:
            assert member.value in system

    def test_every_storable_country_is_offered_to_the_model(self):
        system, _ = receipts.build_prompt()
        for member in TripReportCountry:
            assert member.value in system

    def test_the_model_is_told_which_currencies_exist(self):
        system, _ = receipts.build_prompt()
        for currency in receipts.CURRENCIES:
            assert currency in system


class TestVocabulary:
    def test_an_invented_category_is_refused_not_guessed_at(self):
        """``food_and_drink`` is plausible, unstorable, and must not be mapped.

        Nudging it to ``food`` would be a guess about what the model meant,
        made on a photo nobody re-reads. Refusing sends the driver back to the
        keyboard, which is exactly where they are today.
        """
        with pytest.raises(receipts.ReceiptUnreadable):
            receipts.parse_reading(_answer(category="food_and_drink"))

    def test_an_invented_country_is_refused(self):
        with pytest.raises(receipts.ReceiptUnreadable):
            receipts.parse_reading(_answer(country="kazakhstan"))

    def test_case_and_padding_around_a_real_value_are_forgiven(self):
        """Only the wrapping is normalised; the word itself must be ours."""
        reading = receipts.parse_reading(_answer(country=" KZ ", category="FOOD"))
        assert reading.country is TripReportCountry.kz
        assert reading.category is TripReportExpenseCategory.food

    def test_the_forms_own_label_for_russia_is_understood(self):
        """The paper report calls the Russian column RF, so the model will too.

        This is the one alias worth honouring: the abbreviation comes from this
        product's own vocabulary, not from the model inventing something.
        """
        reading = receipts.parse_reading(_answer(country="rf", currency="rub"))
        assert reading.country is TripReportCountry.ru

    def test_a_missing_category_is_refused(self):
        with pytest.raises(receipts.ReceiptUnreadable):
            receipts.parse_reading(_answer(category=None))


# ── What happens to the numbers ──────────────────────────────────────────


class TestAmount:
    def test_a_total_printed_with_spaces_and_a_comma_is_read_as_printed(self):
        """``12 500,00`` is how a Kazakh receipt prints twelve and a half thousand."""
        reading = receipts.parse_reading(_answer(amount="12 500,00"))
        assert reading.amount == Decimal("12500.00")

    def test_a_dotted_thousands_mark_is_not_read_as_small_change(self):
        """``12.500`` is 12 500 tenge, not 12 tenge 50.

        Three trailing digits after the only separator is a thousands mark
        everywhere on this corridor. Reading it as a decimal would understate the
        line by a factor of a thousand — and a suspiciously small expense is the
        kind of error nobody queries.
        """
        assert receipts.parse_reading(_answer(amount="12.500")).amount == Decimal("12500.00")

    def test_a_decimal_total_keeps_its_kopecks(self):
        assert receipts.parse_reading(_answer(amount="1234.56")).amount == Decimal("1234.56")

    def test_a_currency_sign_printed_next_to_the_total_does_not_break_it(self):
        assert receipts.parse_reading(_answer(amount="₸ 4500")).amount == Decimal("4500.00")

    def test_a_plain_number_survives_untouched(self):
        assert receipts.parse_reading(_answer(amount=4500.5)).amount == Decimal("4500.50")

    @pytest.mark.parametrize("bad", [0, -120, "0", "abc", None, True, [1]])
    def test_a_total_that_is_not_money_is_refused(self, bad):
        """Nothing here is a total, and each would otherwise become one.

        ``True`` is in the list because ``isinstance(True, int)`` holds: without
        an explicit guard a boolean turns into an expense line of exactly 1.
        """
        with pytest.raises(receipts.ReceiptUnreadable):
            receipts.parse_reading(_answer(amount=bad))

    def test_a_total_too_large_for_the_column_is_refused_here(self):
        """Better a 422 than a database error on the driver's save.

        ``TripCountryExpenseLine.amount`` is Numeric(12, 2); a wider number would
        pass this endpoint, sit in the form looking normal, and fail at the far
        end of the flow where the driver can no longer tell what went wrong.
        """
        with pytest.raises(receipts.ReceiptUnreadable):
            receipts.parse_reading(_answer(amount="99999999999999"))


class TestConfidence:
    def test_a_percentage_is_not_rounded_up_into_certainty(self):
        """A model answering ``85`` means 85%, and 1.0 would be a lie.

        Clamping it to 1.0 would dress the shakiest kind of reading as the
        surest, which is the only direction of this error that costs money.
        """
        assert receipts.parse_reading(_answer(confidence=85)).confidence == pytest.approx(0.85)

    def test_a_missing_confidence_is_not_treated_as_a_confident_reading(self):
        reading = receipts.parse_reading(_answer(confidence=None))
        assert reading.confidence == receipts.DEFAULT_CONFIDENCE
        assert reading.confidence < 1.0

    def test_an_unparsable_confidence_falls_back_rather_than_raising(self):
        """The total is still readable; the model's self-assessment is not.

        Throwing the whole reading away over a bad confidence field would cost
        the driver a good scan for a field they never asked for.
        """
        assert receipts.parse_reading(_answer(confidence="very sure")).confidence == (
            receipts.DEFAULT_CONFIDENCE
        )

    @pytest.mark.parametrize("raw,expected", [(150, 1.0), (-3, 0.0), (0.42, 0.42)])
    def test_confidence_always_lands_inside_zero_to_one(self, raw, expected):
        assert receipts.parse_reading(_answer(confidence=raw)).confidence == pytest.approx(expected)


class TestCurrency:
    def test_an_unknown_currency_makes_the_reading_unusable(self):
        """A total with no unit we account in is a number, not an expense.

        ``TripCountryExpenseLine`` has no currency column — the country implies
        it — so a euro total accepted here becomes tenge the moment it is saved.
        """
        with pytest.raises(receipts.ReceiptUnreadable):
            receipts.parse_reading(_answer(currency="eur"))

    def test_a_currency_that_contradicts_the_country_is_pushed_to_low_confidence(self):
        """Rubles on the Kazakh table means the driver is about to accept
        the right digits in the wrong unit, and nothing downstream can notice.

        The reading is still returned — a driver really can pay in rubles in
        Kazakhstan — but it arrives marked as one to look at twice.
        """
        reading = receipts.parse_reading(_answer(country="kz", currency="rub", confidence=0.97))
        assert reading.confidence <= receipts.LOW_CONFIDENCE

    def test_a_matching_currency_keeps_the_confidence_the_model_gave(self):
        reading = receipts.parse_reading(_answer(country="ru", currency="rub", confidence=0.97))
        assert reading.confidence == pytest.approx(0.97)


class TestVendor:
    def test_a_long_vendor_name_is_cut_to_fit(self):
        reading = receipts.parse_reading(_answer(vendor="A" * 400))
        assert len(reading.vendor) == receipts.VENDOR_MAX_LEN

    def test_a_blank_vendor_becomes_nothing_rather_than_an_empty_label(self):
        assert receipts.parse_reading(_answer(vendor="   ")).vendor is None

    def test_a_non_string_vendor_is_dropped_quietly(self):
        assert receipts.parse_reading(_answer(vendor={"name": "x"})).vendor is None


class TestAnswerShape:
    def test_json_wrapped_in_a_code_fence_is_still_read(self):
        """Models fence their JSON often enough that refusing it loses good scans."""
        payload = receipts.extract_json('Here you go:\n```json\n{"amount": 10}\n```')
        assert payload == {"amount": 10}

    def test_an_answer_with_no_json_at_all_is_a_provider_failure(self):
        """Not the driver's problem, so not a 422 — see the router's mapping."""
        with pytest.raises(receipts.ReceiptScanUnavailable):
            receipts.extract_json("I cannot help with that.")

    def test_a_truncated_json_answer_is_a_provider_failure(self):
        with pytest.raises(receipts.ReceiptScanUnavailable):
            receipts.extract_json('{"amount": 10, "country":')


# ── The call itself ──────────────────────────────────────────────────────


class _FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "boom",
                request=httpx.Request("POST", "http://ai"),
                response=httpx.Response(self.status_code),
            )

    def json(self) -> dict:
        return self._payload


class _FakeClient:
    def __init__(self, sent: dict, response: _FakeResponse):
        self._sent = sent
        self._response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> None:
        return None

    async def post(self, url, headers=None, json=None):
        self._sent.update(url=url, headers=headers, body=json)
        return self._response


def _patch_transport(monkeypatch, response: _FakeResponse) -> dict:
    sent: dict = {}
    monkeypatch.setattr(
        receipts.httpx, "AsyncClient", lambda **kwargs: _FakeClient(sent, response)
    )
    return sent


class TestVisionCall:
    async def test_the_photo_actually_travels_with_the_prompt(self, monkeypatch):
        """Without the image attached the model would confabulate from the text alone."""
        monkeypatch.setattr(settings, "ai_api_key", "test-key", raising=False)
        sent = _patch_transport(
            monkeypatch,
            _FakeResponse({"choices": [{"message": {"content": '{"amount": 1}'}}]}),
        )

        await receipts.call_vision(JPEG_BYTES, "image/jpeg")

        parts = sent["body"]["messages"][-1]["content"]
        image_part = next(p for p in parts if p["type"] == "image_url")
        assert image_part["image_url"]["url"].startswith("data:image/jpeg;base64,")

    async def test_a_jpg_content_type_is_normalised_for_the_provider(self, monkeypatch):
        """Browsers and phones send ``image/jpg``; providers only know ``image/jpeg``."""
        monkeypatch.setattr(settings, "ai_api_key", "test-key", raising=False)
        sent = _patch_transport(
            monkeypatch,
            _FakeResponse({"choices": [{"message": {"content": "{}"}}]}),
        )

        await receipts.call_vision(JPEG_BYTES, "image/jpg")

        parts = sent["body"]["messages"][-1]["content"]
        image_part = next(p for p in parts if p["type"] == "image_url")
        assert image_part["image_url"]["url"].startswith("data:image/jpeg;base64,")

    async def test_an_upstream_error_never_reaches_the_driver_verbatim(self, monkeypatch):
        """Provider messages can carry keys, model names and account details."""
        monkeypatch.setattr(settings, "ai_api_key", "test-key", raising=False)
        _patch_transport(monkeypatch, _FakeResponse({}, status_code=500))

        with pytest.raises(receipts.ReceiptScanUnavailable) as exc:
            await receipts.call_vision(JPEG_BYTES, "image/jpeg")
        assert "boom" not in str(exc.value)

    async def test_an_empty_api_key_stops_before_any_network_call(self, monkeypatch):
        monkeypatch.setattr(settings, "ai_api_key", "", raising=False)

        def _explode(**kwargs):
            raise AssertionError("the provider must not be contacted without a key")

        monkeypatch.setattr(receipts.httpx, "AsyncClient", _explode)

        with pytest.raises(receipts.ReceiptScanNotConfigured):
            await receipts.call_vision(JPEG_BYTES, "image/jpeg")


# ── The endpoint ─────────────────────────────────────────────────────────


class TestEndpoint:
    async def test_a_readable_receipt_comes_back_with_its_confidence(
        self, client: AsyncClient, driver_headers, model_says
    ):
        model_says('{"country":"kz","category":"parking","amount":"2 500,00",'
                   '"currency":"kzt","vendor":"Stoyanka Aktobe","confidence":0.82}')

        res = await client.post(SCAN_PATH, headers=driver_headers, files=_upload())

        assert res.status_code == 200, res.text
        body = res.json()
        assert body["country"] == "kz"
        assert body["category"] == "parking"
        assert body["amount"] == 2500.0
        assert body["currency"] == "kzt"
        assert body["vendor"] == "Stoyanka Aktobe"
        assert body["confidence"] == pytest.approx(0.82)

    async def test_a_scan_writes_nothing_at_all(
        self, client: AsyncClient, db, driver_headers, model_says
    ):
        """The point of the whole endpoint: a reading is a suggestion.

        If a scan could create a row, a misread total would become an expense
        record nobody typed and nobody reviews — the exact failure this feature
        exists to avoid, dressed up as automation.
        """
        model_says('{"country":"ru","category":"repair","amount":9000,'
                   '"currency":"rub","vendor":"SТО","confidence":0.7}')

        res = await client.post(SCAN_PATH, headers=driver_headers, files=_upload())
        assert res.status_code == 200, res.text

        for model in (TripExpenseReport, TripCountryExpenseLine, DriverExpense):
            count = await db.scalar(select(func.count()).select_from(model))
            assert count == 0, f"{model.__name__} rows were created by a scan"

    async def test_a_signed_out_phone_cannot_scan(self, client: AsyncClient, model_says):
        model_says('{"country":"kz","category":"food","amount":1,"currency":"kzt"}')
        res = await client.post(SCAN_PATH, files=_upload())
        assert res.status_code == 401

    async def test_an_invented_category_is_a_clean_422_not_a_server_error(
        self, client: AsyncClient, driver_headers, model_says
    ):
        """Asking a model for an enum member sometimes gets a near-miss back.

        That is a routine outcome, not a fault: the driver types the line by
        hand, which is what they do today. A 500 would page somebody for it.
        """
        model_says('{"country":"kz","category":"food_and_drink","amount":1200,'
                   '"currency":"kzt","confidence":0.9}')

        res = await client.post(SCAN_PATH, headers=driver_headers, files=_upload())

        assert res.status_code == 422, res.text
        assert "category" in res.json()["detail"].lower()

    async def test_a_photo_with_no_readable_total_is_a_422(
        self, client: AsyncClient, driver_headers, model_says
    ):
        model_says('{"country":null,"category":null,"amount":null,'
                   '"currency":null,"vendor":null,"confidence":0}')
        res = await client.post(SCAN_PATH, headers=driver_headers, files=_upload())
        assert res.status_code == 422

    async def test_a_provider_outage_is_a_bad_gateway(
        self, client: AsyncClient, driver_headers, monkeypatch
    ):
        async def _down(image: bytes, content_type: str) -> str:
            raise receipts.ReceiptScanUnavailable("The receipt reading service is unavailable")

        monkeypatch.setattr(receipts, "call_vision", _down)

        res = await client.post(SCAN_PATH, headers=driver_headers, files=_upload())
        assert res.status_code == 502

    async def test_a_server_without_an_api_key_says_so_instead_of_failing(
        self, client: AsyncClient, driver_headers, monkeypatch
    ):
        """Most deployments never set a key; that must read as "off", not "broken"."""
        monkeypatch.setattr(settings, "ai_api_key", "", raising=False)

        res = await client.post(SCAN_PATH, headers=driver_headers, files=_upload())

        assert res.status_code == 503, res.text
        assert "not configured" in res.json()["detail"].lower()

    async def test_a_pdf_is_refused_before_the_model_is_ever_paid_for(
        self, client: AsyncClient, driver_headers, monkeypatch
    ):
        async def _explode(image: bytes, content_type: str) -> str:
            raise AssertionError("a rejected upload must not reach the provider")

        monkeypatch.setattr(receipts, "call_vision", _explode)

        res = await client.post(
            SCAN_PATH,
            headers=driver_headers,
            files={"file": ("scan.pdf", b"%PDF-1.4", "application/pdf")},
        )
        assert res.status_code == 415

    async def test_an_iphone_original_is_refused_at_the_door(
        self, client: AsyncClient, driver_headers, monkeypatch
    ):
        """HEIC uploads happily and then fails inside the provider.

        A 415 that says "retake the photo" is something a driver at a truck stop
        can act on; a 502 thirty seconds later is not.
        """
        monkeypatch.setattr(
            receipts,
            "call_vision",
            lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not be called")),
        )

        res = await client.post(
            SCAN_PATH,
            headers=driver_headers,
            files={"file": ("IMG_0001.HEIC", JPEG_BYTES, "image/heic")},
        )
        assert res.status_code == 415

    async def test_a_charset_suffix_on_the_content_type_is_tolerated(
        self, client: AsyncClient, driver_headers, model_says
    ):
        """Some HTTP clients append parameters; the type is still an image."""
        model_says('{"country":"uz","category":"taxi","amount":50000,'
                   '"currency":"uzs","confidence":0.6}')

        res = await client.post(
            SCAN_PATH,
            headers=driver_headers,
            files={"file": ("receipt.jpg", JPEG_BYTES, "image/jpeg; charset=binary")},
        )
        assert res.status_code == 200, res.text

    async def test_an_oversized_photo_is_refused(
        self, client: AsyncClient, driver_headers, monkeypatch
    ):
        """The image is base64'd into the prompt, so bytes here are tokens upstream."""

        async def _explode(image: bytes, content_type: str) -> str:
            raise AssertionError("an oversized upload must not reach the provider")

        monkeypatch.setattr(receipts, "call_vision", _explode)
        oversized = b"\xff\xd8\xff\xe0" + b"0" * (receipts.MAX_IMAGE_BYTES + 1)

        res = await client.post(
            SCAN_PATH,
            headers=driver_headers,
            files={"file": ("huge.jpg", oversized, "image/jpeg")},
        )
        assert res.status_code == 413

    async def test_an_empty_upload_is_rejected_rather_than_scanned(
        self, client: AsyncClient, driver_headers, monkeypatch
    ):
        async def _explode(image: bytes, content_type: str) -> str:
            raise AssertionError("an empty upload must not reach the provider")

        monkeypatch.setattr(receipts, "call_vision", _explode)

        res = await client.post(
            SCAN_PATH,
            headers=driver_headers,
            files={"file": ("empty.jpg", b"", "image/jpeg")},
        )
        assert res.status_code == 400
