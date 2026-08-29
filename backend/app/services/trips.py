"""Trip helpers: human references and profit-per-trip computation."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from sqlalchemy import BigInteger, case, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.driver_app import DriverExpense
from app.models.maintenance import FuelLog
from app.models.trips import Trip


REFERENCE_WIDTH = 6


def _reference_lock_key(org_id, year: int) -> int:
    """Deterministic 64-bit advisory-lock key for one org's yearly sequence.

    Must be stable across processes — Python's built-in ``hash()`` is salted per
    interpreter, so two uvicorn workers would derive different keys and the lock
    would guard nothing. blake2b gives the same number everywhere.
    """
    digest = hashlib.blake2b(
        f"trip-reference:{org_id}:{year}".encode(), digest_size=8
    ).digest()
    return int.from_bytes(digest, "big", signed=True)  # pg advisory keys are int8


async def generate_reference(db: AsyncSession, org_id) -> str:
    """Next sequential reference for *one organization*, e.g. TR-2026-000042.

    Scoped to ``org_id``: numbering is per tenant, so every customer's first trip
    of the year is TR-YYYY-000001 and no customer can infer another's volume from
    their own trip numbers.

    Derived from the highest existing reference rather than a row count — with a
    count, deleting trip 42 leaves the next trip computing 42 again while trip 43
    still holds it, and the insert fails for no visible reason.

    The maximum is taken **numerically**, not lexicographically. Production holds
    seeded trips numbered ``TR-2026-0094`` (four digits) alongside generated ones
    at six, and as text ``'TR-2026-0094' > 'TR-2026-000095'`` — the '9' beats the
    '0' in the third position. A string MAX therefore sticks on the short
    reference forever, hands out the same number on every call, and the tenant
    can never create a second trip. Casting the suffix is what makes mixed widths
    safe. The CASE guard keeps the cast away from any row whose suffix is not
    all digits (a hand-typed ``TR-2026-ACME``), which would otherwise raise.

    **Serialized with a transaction-scoped advisory lock.** Reading the maximum
    and inserting the new row is otherwise a classic read-then-write race: N
    dispatchers clicking "create" at the same instant all read the same maximum,
    N-1 lose at the unique constraint, and each retry re-runs the race, so a
    burst needs O(N) attempts to drain and the last user just sees an error. The
    lock is held only until the caller's transaction ends (microseconds — one
    INSERT), is keyed per org+year so tenants never block each other, and is
    released automatically on commit *or* rollback, so a failed create cannot
    strand it.

    The unique constraint remains the actual guarantee; this only stops honest
    concurrent creates from having to fight over it.
    """
    year = datetime.now(timezone.utc).year

    if not settings.is_sqlite():  # advisory locks are a Postgres feature
        await db.execute(select(func.pg_advisory_xact_lock(_reference_lock_key(org_id, year))))

    prefix = f"TR-{year}-"
    # Only rows whose suffix is entirely digits reach the cast; anything else
    # (a hand-typed TR-2026-ACME) yields NULL and is ignored by max().
    numeric_suffix = case(
        (
            Trip.reference.op("~")(f"^{prefix}[0-9]+$"),
            cast(func.substr(Trip.reference, len(prefix) + 1), BigInteger),
        ),
        else_=None,
    )
    seq = (
        await db.execute(
            select(func.max(numeric_suffix)).where(
                Trip.org_id == org_id, Trip.reference.like(f"{prefix}%")
            )
        )
    ).scalar() or 0

    return f"{prefix}{seq + 1:0{REFERENCE_WIDTH}d}"


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
