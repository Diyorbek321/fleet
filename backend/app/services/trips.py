"""Trip helpers: human references and profit-per-trip computation."""
from __future__ import annotations

import hashlib
import re

from sqlalchemy import BigInteger, case, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.driver_app import DriverExpense
from app.models.maintenance import FuelLog
from app.models.organizations import Organization
from app.models.trips import Trip


REFERENCE_WIDTH = 4

# ``trips.reference`` is String(40). Reserve the separator and room for a
# sequence that outgrows its padding, so a long company name is shortened here
# rather than by the database rejecting the insert.
MAX_PREFIX_LEN = 40 - 1 - 8

# What the scheme produced before references were named after the company.
# Still counted below, so switching a live tenant over continues their numbering
# instead of restarting at 1 on top of trips they already have.
_LEGACY_RE = r"^TR-[0-9]{4}-[0-9]+$"

# The sequence is whatever digits end the reference — true under both schemes.
_TAIL_RE = r"[0-9]+$"


def _reference_lock_key(org_id) -> int:
    """Deterministic 64-bit advisory-lock key for one org's sequence.

    Must be stable across processes — Python's built-in ``hash()`` is salted per
    interpreter, so two uvicorn workers would derive different keys and the lock
    would guard nothing. blake2b gives the same number everywhere.
    """
    digest = hashlib.blake2b(f"trip-reference:{org_id}".encode(), digest_size=8).digest()
    return int.from_bytes(digest, "big", signed=True)  # pg advisory keys are int8


def reference_prefix(org_name: str | None) -> str:
    """The company's own name, as it will read at the head of a reference.

    Internal whitespace is collapsed rather than removed: "Angren Tek" is how
    the customer writes it and how they expect to read it back on a CMR. Only
    characters that would break a filename or a URL are dropped, because a
    reference ends up in both.

    Falls back to ``TR`` for an unnamed organization, so a reference is never
    generated as a bare number.
    """
    cleaned = re.sub(r"[^\w \-.]", "", org_name or "", flags=re.UNICODE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -.")
    return cleaned[:MAX_PREFIX_LEN].strip(" -.") or "TR"


def _like_escape(value: str) -> str:
    """Neutralise LIKE wildcards in a literal prefix (escape char is ``\\``)."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def generate_reference(db: AsyncSession, org_id) -> str:
    """Next sequential reference for *one organization*, e.g. ``Angren Tek-0012``.

    Named after the company rather than an opaque ``TR-YYYY-NNNNNN``, because
    every audience for a reference is external — it is read out on the phone,
    printed on the CMR, and pushed to the cargo owner in Telegram — and none of
    them can tell one fleet's ``TR-2026-0012`` from another's.

    Scoped to ``org_id``: numbering is per tenant, so no customer can infer
    another's volume from their own trip numbers.

    Derived from the highest existing reference rather than a row count — with a
    count, deleting trip 42 leaves the next trip computing 42 again while trip 43
    still holds it, and the insert fails for no visible reason.

    The maximum is taken **numerically**, not lexicographically, and over both
    the current prefix and the legacy ``TR-YYYY-`` one. Numerically, because as
    text ``'...-0094' > '...-000095'`` — the '9' beats the '0' in the third
    position — so a string MAX sticks on the shortest reference forever and the
    tenant can never create a second trip. Over both schemes, because a fleet
    already running at ``TR-2026-0012`` should continue at 13 rather than open a
    second sequence at 1 beside it. The CASE guard keeps the cast away from any
    row whose tail is not all digits (a hand-typed ``TR-2026-ACME``), which
    would otherwise raise.

    **Serialized with a transaction-scoped advisory lock.** Reading the maximum
    and inserting the new row is otherwise a classic read-then-write race: N
    dispatchers clicking "create" at the same instant all read the same maximum,
    N-1 lose at the unique constraint, and each retry re-runs the race, so a
    burst needs O(N) attempts to drain and the last user just sees an error. The
    lock is held only until the caller's transaction ends (microseconds — one
    INSERT), is keyed per org so tenants never block each other, and is released
    automatically on commit *or* rollback, so a failed create cannot strand it.

    The unique constraint remains the actual guarantee; this only stops honest
    concurrent creates from having to fight over it.
    """
    if not settings.is_sqlite():  # advisory locks are a Postgres feature
        await db.execute(select(func.pg_advisory_xact_lock(_reference_lock_key(org_id))))

    org_name = (
        await db.execute(select(Organization.name).where(Organization.id == org_id))
    ).scalar_one_or_none()
    prefix = reference_prefix(org_name)

    matches = Trip.reference.op("~")(f"^{re.escape(prefix)}-[0-9]+$") | Trip.reference.op("~")(
        _LEGACY_RE
    )
    numeric_tail = case(
        (matches, cast(func.substring(Trip.reference, _TAIL_RE), BigInteger)),
        else_=None,
    )

    seq = (
        await db.execute(
            select(func.max(numeric_tail)).where(
                Trip.org_id == org_id,
                # Narrows the scan to this tenant's candidate rows before the
                # regexes run; the regexes above are what actually decide.
                Trip.reference.like(f"{_like_escape(prefix)}-%", escape="\\")
                | Trip.reference.like("TR-%"),
            )
        )
    ).scalar() or 0

    return f"{prefix}-{seq + 1:0{REFERENCE_WIDTH}d}"


async def compute_trip_pnl(db: AsyncSession, trip: Trip) -> dict:
    """Revenue minus reconciled fuel + driver expenses for one trip."""
    fuel_cost = (
        await db.execute(
            select(func.coalesce(func.sum(FuelLog.total_cost), 0)).where(FuelLog.trip_id == trip.id)
        )
    ).scalar() or 0
    expense_cost = (
        await db.execute(
            select(func.coalesce(func.sum(DriverExpense.amount), 0)).where(DriverExpense.trip_id == trip.id)
        )
    ).scalar() or 0

    revenue = float(trip.rate or 0)
    fuel_cost = float(fuel_cost)
    expense_cost = float(expense_cost)
    total_cost = fuel_cost + expense_cost
    profit = revenue - total_cost
    margin = (profit / revenue * 100.0) if revenue > 0 else 0.0

    return {
        "trip_id": trip.id,
        "reference": trip.reference,
        "status": trip.status,
        "currency": trip.currency,
        "revenue": round(revenue, 2),
        "fuel_cost": round(fuel_cost, 2),
        "expense_cost": round(expense_cost, 2),
        "total_cost": round(total_cost, 2),
        "profit": round(profit, 2),
        "margin_pct": round(margin, 1),
    }
