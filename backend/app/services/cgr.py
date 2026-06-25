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
import urllib.parse
from dataclasses import dataclass
from datetime import datetime
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


def normalize_status(ru_label: str) -> CgrStatus:
    return _RU_STATUS_MAP.get(ru_label.strip().lower(), CgrStatus.unknown)


@dataclass(frozen=True)
class BookingRecord:
    plate: str
    checkpoint: str
    queue_at: Optional[datetime]
    status: CgrStatus
    raw_status: str


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

    INTEGRATION TODO (verify against live page via devtools, then adjust only here):
      - The exact query-param name for plate search on /ru/registry/public-list
        (placeholder: ``number``).
      - The results table row/cell selectors in ``_parse_public_list``.
    These are the only unknowns; the rest of the system is independent of them.
    """

    PUBLIC_LIST_PATH = "/ru/registry/public-list"

    def __init__(self, base_url: str = CGR_BASE, timeout: float = 15.0) -> None:
        self._base = base_url.rstrip("/")
        self._timeout = timeout

    async def lookup_truck(self, plate: str) -> Optional[BookingRecord]:
        async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=True) as client:
            resp = await client.get(
                f"{self._base}{self.PUBLIC_LIST_PATH}",
                params={"number": plate},
            )
            resp.raise_for_status()
        return self._parse_public_list(resp.text, plate)

    @staticmethod
    def _parse_public_list(html: str, plate: str) -> Optional[BookingRecord]:
        """Parse the first matching row from the public registry HTML table.

        Selectors are isolated here pending live verification (see class TODO).
        """
        from bs4 import BeautifulSoup  # lazy import: only needed for the real fetch

        soup = BeautifulSoup(html, "html.parser")
        table = soup.find("table")
        if table is None:
            return None

        target = plate.replace(" ", "").upper()
        for row in table.find_all("tr"):
            cells = [c.get_text(strip=True) for c in row.find_all("td")]
            if len(cells) < 4:
                continue
            checkpoint, row_plate, queue_at_text, status_text = cells[0], cells[1], cells[2], cells[3]
            if row_plate.replace(" ", "").upper() != target:
                continue
            return BookingRecord(
                plate=row_plate,
                checkpoint=checkpoint,
                queue_at=_parse_dt(queue_at_text),
                status=normalize_status(status_text),
                raw_status=status_text,
            )
        return None


def _parse_dt(text: str) -> Optional[datetime]:
    for fmt in ("%d.%m.%Y %H:%M", "%d.%m.%Y %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(text.strip(), fmt)
        except ValueError:
            continue
    return None


# Module-level default. Overridable in tests via ``app.dependency_overrides``.
_default_client: CgrClient = HttpCgrClient()


def get_cgr_client() -> CgrClient:
    return _default_client
