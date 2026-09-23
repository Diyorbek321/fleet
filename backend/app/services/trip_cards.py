"""Builds the cargo owner's card — the one message shape they ever receive.

Both reasons to write to a customer end up here: the morning digest and a
checkpoint the driver just reported. Keeping the assembly in one place is what
makes those two identical; when it lived at each call site they drifted within
a month, and a customer comparing yesterday's message to today's spent the
first ten seconds working out which fields moved.

The inputs a card needs beyond the trip itself — who the fleet is, which lorry,
where it is standing, when it reaches customs — are gathered here rather than by
the callers, because three of the four are a query and the fourth is an
estimate, and no notification path should have to know that.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger
from app.core.urls import track_url
from app.models.organizations import Organization
from app.models.trips import Trip
from app.models.trucks import Truck
from app.services import eta as eta_service
from app.services.telegram import format_customer_card

__all__ = ["build_customer_card"]


async def build_customer_card(
    db: AsyncSession,
    trip: Trip,
    *,
    lat: float | None,
    lng: float | None,
    place: str | None,
    now: datetime | None = None,
    note: str | None = None,
    token: str | None = None,
) -> str:
    """The card for one trip, ready to send.

    ``token`` is the recipient's own subscription token, and it is a per-send
    argument rather than part of the trip because the map link it becomes is
    the one thing in the card that differs between two people watching the same
    lorry. Omitted, the card simply carries no link.

    Never raises on the estimate: an arrival date that cannot be worked out is
    a line the card leaves out, not a message that fails to arrive. The load's
    position is the point of writing at all.
    """
    org_name = (
        await db.execute(select(Organization.name).where(Organization.id == trip.org_id))
    ).scalar_one_or_none() or "—"

    plate = None
    if trip.truck_id is not None:
        plate = (
            await db.execute(select(Truck.plate_number).where(Truck.id == trip.truck_id))
        ).scalar_one_or_none()

    estimate = None
    try:
        estimate = await eta_service.estimate_customs_arrival(
            db,
            trip,
            current_lat=lat,
            current_lng=lng,
            covered_km=_distance_made_good(trip, lat, lng),
            now=now,
        )
    except Exception:  # noqa: BLE001 — an estimate is never worth a lost message
        logger.exception("trip_card_eta_failed", trip_id=str(trip.id))

    return format_customer_card(
        org_name=org_name,
        reference=trip.reference,
        origin=trip.origin_name,
        destination=trip.destination_name,
        loaded_at=trip.loaded_at,
        plate=plate,
        place=place,
        lat=lat,
        lng=lng,
        eta_customs=estimate.day if estimate else None,
        eta_is_measured=bool(estimate and estimate.is_measured),
        cargo=trip.cargo_description,
        note=note,
        track_url=track_url(token),
    )


def _distance_made_good(trip: Trip, lat: float | None, lng: float | None) -> float:
    """How far the load has got from its origin, in road kilometres.

    Deliberately distance *made good* rather than distance driven: it is what
    the trip's own pace should be measured against, and it errs on the low side
    whenever a route bends, which pushes the estimate later rather than
    earlier. A date that slips is a complaint; a date that arrives early is not.
    """
    if lat is None or lng is None:
        return 0.0
    if trip.origin_lat is None or trip.origin_lng is None:
        return 0.0
    return eta_service.road_km(
        float(trip.origin_lat), float(trip.origin_lng), float(lat), float(lng)
    )
