"""CarGoRuqsat (cgr.qoldau.kz) integration — the single boundary to the external site.

What this does and does NOT do
------------------------------
- We CANNOT create a booking from here. Booking on CarGoRuqsat legally requires
  the driver's ЭЦП (digital signature) + SMS/biometric MFA, and there is no public
  "create booking" API. Automating that is out of scope by design.
- We CAN read the PUBLIC booking registry (no login) to track a truck's queue
  status by plate, and we hand the driver off to the official flow to actually book.

Everything that touches the external site lives behind the ``CgrClient`` protocol so
our queue logic stays testable with a fake, and the real HTML/endpoint details are
confined to ``HttpCgrClient`` — the one place to finalize once verified against the
live page via browser devtools.
"""
from __future__ import annotations

import enum
import re
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Optional, Protocol, runtime_checkable

import httpx

CGR_BASE = "https://cgr.qoldau.kz"


class CgrStatus(str, enum.Enum):
    in_queue = "in_queue"
    late = "late"
    crossed = "crossed"
    check_failed = "check_failed"
    revoked = "revoked"
    unknown = "unknown"


# Maps the Russian labels shown in the public registry to our normalized statuses.
_RU_STATUS_MAP: dict[str, CgrStatus] = {
    "в очереди": CgrStatus.in_queue,
    "опаздывает": CgrStatus.late,
    "пересёк пункт пропуска": CgrStatus.crossed,
    "пересек пункт пропуска": CgrStatus.crossed,
    "проверка провалена": CgrStatus.check_failed,
    "пропуск отозван": CgrStatus.revoked,
}


# When a row carries several badges at once we report the one the driver has to
# act on. "В очереди" plus "Опаздывает" is the common pair: still booked, but
# running late — and "late" is the half worth waking someone up for. Ordered
# most- to least-urgent; the first match wins.
_STATUS_PRIORITY: tuple[CgrStatus, ...] = (
    CgrStatus.revoked,
    CgrStatus.check_failed,
    CgrStatus.late,
    CgrStatus.crossed,
    CgrStatus.in_queue,
)


def normalize_status(ru_label: str) -> CgrStatus:
    """Map the registry's Russian status text onto one of ours.

    The text may hold more than one label. The site renders each as its own
    ``<span class="badge">``, so what arrives here is their concatenation —
    matching the whole string against the map returns ``unknown`` and the
    driver is told nothing at all. Match on substrings instead and rank.
    """
    text = " ".join(ru_label.split()).lower()
    if not text:
        return CgrStatus.unknown

    exact = _RU_STATUS_MAP.get(text)
    if exact is not None:
        return exact

    found = {status for label, status in _RU_STATUS_MAP.items() if label in text}
    for status in _STATUS_PRIORITY:
        if status in found:
            return status
    return CgrStatus.unknown


@dataclass(frozen=True)
class BookingRecord:
    """One truck's booking as the public registry currently shows it.

    ``queue_at``/``queue_until`` are the ends of a slot, not an instant: the
    registry books an hour-long window ("29.08.2026", "00:00-01:00") and the
    driver has to present within it. We keep both so the app can say "by 01:00"
    rather than just naming a start time that has already passed.
    """

    plate: str
    checkpoint: str
    queue_at: Optional[datetime]
    status: CgrStatus
    raw_status: str
    queue_until: Optional[datetime] = None


def build_booking_handoff_url(checkpoint: Optional[str] = None, plate: Optional[str] = None) -> str:
    """Deep link to the official CarGoRuqsat start page where the driver books.

    The driver completes ЭЦП/SMS there; we only pre-point them at it. Query params
    are best-effort hints — the official flow ignores unknown ones harmlessly.
    """
    params = {k: v for k, v in (("checkpoint", checkpoint), ("truck", plate)) if v}
    query = ("?" + urllib.parse.urlencode(params)) if params else ""
    return f"{CGR_BASE}/ru/start{query}"


@runtime_checkable
class CgrClient(Protocol):
    """Boundary to CarGoRuqsat. Implemented by ``HttpCgrClient`` (real) and fakes (tests)."""

    async def lookup_truck(self, plate: str) -> Optional[BookingRecord]:
        """Return the current public-registry booking for ``plate``, or None if none found."""
        ...


class HttpCgrClient:
    """Reads the public booking registry over HTTP. No authentication required.

    Verified against the live page; ``tests/test_cgr.py`` pins both the request
    and the parsing, and its ``live``-marked tests re-check them against the
    real site on demand.
    """

    PUBLIC_LIST_PATH = "/ru/registry/public-list"

    # The registry's own filter field name. Getting this wrong is silent: the
    # site ignores an unrecognised query parameter and serves the unfiltered
    # first page, so every lookup "succeeds" and finds the truck only by
    # coincidence.
    PLATE_PARAM = "flTruckNumber"

    def __init__(
        self,
        base_url: str = CGR_BASE,
        timeout: float = 15.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._timeout = timeout
        # Only tests pass a transport; it is the seam that lets them assert on
        # the outgoing request without reaching the network.
        self._transport = transport

    async def lookup_truck(self, plate: str) -> Optional[BookingRecord]:
        async with httpx.AsyncClient(
            timeout=self._timeout, follow_redirects=True, transport=self._transport
        ) as client:
            resp = await client.get(
                f"{self._base}{self.PUBLIC_LIST_PATH}",
                params={self.PLATE_PARAM: plate},
            )
            resp.raise_for_status()
        return self._parse_public_list(resp.text, plate)

    @staticmethod
    def _parse_public_list(html: str, plate: str) -> Optional[BookingRecord]:
        """Parse the row for ``plate`` out of the public registry table.

        Every cell wraps its content in nested ``<span>``/``<div>`` elements —
        the date is two sibling spans, a status can be two badges — so the text
        is extracted with an explicit separator. ``get_text(strip=True)`` runs
        the siblings together and yields "29.08.202600:00-01:00", which no date
        format parses, and "В очередиОпаздывает", which no status label
        matches. Both then fail silently, leaving a record that says nothing.
        """
        from bs4 import BeautifulSoup  # lazy import: only needed for the real fetch

        soup = BeautifulSoup(html, "html.parser")
        table = soup.find("table")
        if table is None:
            return None

        target = _normalize_plate(plate)
        for row in table.find_all("tr"):
            cells = [" ".join(c.get_text(" ", strip=True).split()) for c in row.find_all("td")]
            if len(cells) < 4:
                continue
            checkpoint, row_plate, window_text, status_text = cells[0], cells[1], cells[2], cells[3]
            if _normalize_plate(row_plate) != target:
                continue
            queue_at, queue_until = _parse_queue_window(window_text)
            return BookingRecord(
                plate=_normalize_plate(row_plate),
                checkpoint=checkpoint,
                queue_at=queue_at,
                queue_until=queue_until,
                status=normalize_status(status_text),
                raw_status=status_text,
            )
        return None


def _normalize_plate(plate: str) -> str:
    """Plates are compared and stored without spacing, in upper case.

    The registry pads them for display and drivers type them however they like;
    neither should decide whether a lookup matches.
    """
    return "".join(plate.split()).upper()


# "29.08.2026 00:00-01:00" — a date followed by an hour-long slot.
_WINDOW_RE = re.compile(
    r"(?P<date>\d{2}\.\d{2}\.\d{4})\s*"
    r"(?:(?P<start>\d{2}:\d{2})\s*-\s*(?P<end>\d{2}:\d{2}))?"
)


def _parse_queue_window(text: str) -> tuple[Optional[datetime], Optional[datetime]]:
    """Split the registry's queue cell into the start and end of the slot."""
    match = _WINDOW_RE.search(text)
    if match is None:
        # Fall back to a plain timestamp, in case the site ever renders one.
        for fmt in ("%d.%m.%Y %H:%M", "%d.%m.%Y %H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                return datetime.strptime(text.strip(), fmt), None
            except ValueError:
                continue
        return None, None

    day = datetime.strptime(match.group("date"), "%d.%m.%Y")
    if not match.group("start"):
        return day, None

    start = datetime.combine(day.date(), time.fromisoformat(match.group("start")))
    end = datetime.combine(day.date(), time.fromisoformat(match.group("end")))
    # A slot printed as 23:00-00:00 ends on the following day; without this the
    # window reads as negative and any "you have N minutes left" is nonsense.
    if end <= start:
        end += timedelta(days=1)
    return start, end


# Module-level default. Overridable in tests via ``app.dependency_overrides``.
_default_client: CgrClient = HttpCgrClient()


def get_cgr_client() -> CgrClient:
    return _default_client
