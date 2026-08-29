"""Parsing the live CarGoRuqsat public registry.

``tests/test_queue.py`` covers our own watch/notify logic against a fake client.
This file covers the other half — the boundary to the real site — because that
is where the failure actually was: every unit test passed while the integration
returned nothing at all in production.

The fixture is markup captured verbatim from the live page, so these tests fail
if the parser regresses, and the ``live`` test fails if the site itself changes
shape underneath us.
"""
from __future__ import annotations

import pathlib
from datetime import datetime

import httpx
import pytest
from bs4 import BeautifulSoup

from app.services.cgr import (
    CGR_BASE,
    BookingRecord,
    CgrStatus,
    HttpCgrClient,
    normalize_status,
)

FIXTURE = (pathlib.Path(__file__).parent / "fixtures" / "cgr_public_list.html").read_text(
    encoding="utf-8"
)

REVOKED_PLATE = "877AET01"  # the row whose only badge is "Пропуск отозван"


def _parse(plate: str) -> BookingRecord | None:
    return HttpCgrClient._parse_public_list(FIXTURE, plate)


def _plates_in(html: str) -> list[str]:
    """Every plate the table shows, read independently of the code under test."""
    plates = []
    for row in BeautifulSoup(html, "html.parser").find_all("tr"):
        cells = row.find_all("td")
        if len(cells) >= 4:
            plates.append(cells[1].get_text(" ", strip=True).replace(" ", ""))
    return plates


class TestParsePublicList:
    def test_finds_the_requested_plate(self):
        rec = _parse(REVOKED_PLATE)
        assert rec is not None
        assert rec.plate == REVOKED_PLATE
        assert rec.checkpoint == "Нур Жолы - Хоргос"

    def test_plate_is_not_polluted_by_its_decoration(self):
        """The plate sits between two decorative <span> bullets in the real markup.

        Whatever separator keeps sibling elements apart must not survive into
        the plate itself, or every use downstream — matching, display, the
        notification text — carries stray whitespace.
        """
        rec = _parse(REVOKED_PLATE)
        assert rec is not None
        assert rec.plate == REVOKED_PLATE
        assert " " not in rec.plate

    def test_queue_window_start_is_parsed(self):
        """The date cell is two sibling spans: "29.08.2026" then "00:00-01:00".

        It is a booking *window*, not an instant. We store its start — the time
        the driver has to be there by.
        """
        rec = _parse(REVOKED_PLATE)
        assert rec is not None
        assert rec.queue_at == datetime(2026, 8, 29, 0, 0)

    def test_queue_window_end_is_kept(self):
        rec = _parse(REVOKED_PLATE)
        assert rec is not None
        assert rec.queue_until == datetime(2026, 8, 29, 1, 0)

    def test_single_status_badge(self):
        rec = _parse(REVOKED_PLATE)
        assert rec is not None
        assert rec.status is CgrStatus.revoked

    def test_two_status_badges_resolve_to_the_urgent_one(self):
        """A row can carry both "В очереди" and "Опаздывает" at once.

        Running them together as one label yields ``unknown`` and the driver is
        told nothing; being late is the half they have to act on.
        """
        late = [
            rec
            for rec in (_parse(p) for p in _plates_in(FIXTURE))
            if rec is not None and "Опаздывает" in rec.raw_status
        ]
        assert late, "fixture should contain a row with the two-badge status"
        assert all(rec.status is CgrStatus.late for rec in late)

    def test_unknown_plate_returns_none(self):
        assert _parse("00XYZ00") is None

    def test_plate_match_ignores_spacing_and_case(self):
        assert _parse(" 877aet01 ") is not None

    def test_no_table_returns_none(self):
        assert HttpCgrClient._parse_public_list("<html><body>nothing</body></html>", "X") is None


class TestNormalizeStatus:
    @pytest.mark.parametrize(
        "label,expected",
        [
            ("В очереди", CgrStatus.in_queue),
            ("Опаздывает", CgrStatus.late),
            ("Пропуск отозван", CgrStatus.revoked),
            ("Пересёк пункт пропуска", CgrStatus.crossed),
            ("Проверка провалена", CgrStatus.check_failed),
            ("что-то новое", CgrStatus.unknown),
        ],
    )
    def test_known_labels(self, label, expected):
        assert normalize_status(label) is expected

    def test_late_wins_when_both_labels_are_present(self):
        assert normalize_status("В очереди Опаздывает") is CgrStatus.late


class TestLookupTruck:
    async def test_sends_the_filter_the_site_actually_reads(self):
        """The site ignores an unrecognised filter and returns the whole registry.

        That is what made this feature look empty rather than broken: with the
        wrong parameter name every lookup received page 1 of everyone's
        bookings, so a truck was "found" only if it happened to appear there.
        """
        seen: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen.update(dict(request.url.params))
            return httpx.Response(200, text=FIXTURE)

        client = HttpCgrClient(transport=httpx.MockTransport(handler))
        rec = await client.lookup_truck(REVOKED_PLATE)

        assert seen == {"flTruckNumber": REVOKED_PLATE}
        assert rec is not None and rec.plate == REVOKED_PLATE


@pytest.mark.live
class TestAgainstTheLiveSite:
    """Opt-in: ``pytest -m live``. Excluded from the default run and from CI.

    The tests above prove the parser handles the markup we captured; only this
    one notices when the site stops producing that markup. Without it the suite
    stays green through an outage that returns nothing to every customer.
    """

    async def test_registry_still_has_the_shape_we_parse(self):
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as http:
            resp = await http.get(f"{CGR_BASE}{HttpCgrClient.PUBLIC_LIST_PATH}")
            resp.raise_for_status()

        table = BeautifulSoup(resp.text, "html.parser").find("table")
        assert table is not None, "public registry no longer renders a <table>"

        plates = _plates_in(str(table))
        assert plates, "registry table has no data rows in the shape we parse"

        found = [
            rec
            for rec in (HttpCgrClient._parse_public_list(str(table), p) for p in plates[:3])
            if rec is not None
        ]
        assert found, "could not parse a single row the live page is showing"
        assert any(r.queue_at is not None for r in found), "queue window no longer parses"
        assert any(r.status is not CgrStatus.unknown for r in found), "status labels changed"

    async def test_the_plate_filter_still_narrows_the_result(self):
        """If the filter silently stops working we are back to scanning page 1."""
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as http:
            everything = await http.get(f"{CGR_BASE}{HttpCgrClient.PUBLIC_LIST_PATH}")
            everything.raise_for_status()

        plates = _plates_in(everything.text)
        assert plates, "no rows to pick a probe plate from"
        probe = plates[0]

        client = HttpCgrClient()
        rec = await client.lookup_truck(probe)
        assert rec is not None, f"filtering by {probe} returned nothing"
        assert rec.plate.replace(" ", "").upper() == probe.upper()
