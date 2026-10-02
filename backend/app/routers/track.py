"""The cargo owner's map — one load, no account.

A customer who is told "your lorry is at 43.21, 68.90" has been given a fact
they cannot use. This endpoint backs a public page that shows the same lorry on
a map with its plate above it, the route it is running, and the arrival date
the card already quotes.

**Authentication is the token itself**, the same one already in the customer's
Telegram deep link (``t.me/<bot>?start=trip_<token>``): 32+ URL-safe random
characters, minted per subscription, revocable by regenerating it, and scoped
to exactly one trip. Deliberately not an account — the customer is not our
tenant, and making them one to see where their own freight is would mean nobody
ever looks.

What it deliberately does **not** expose: the fleet's other trucks, the trip's
rate, the driver's identity or phone, and anything belonging to another org. A
leaked token costs the position of one load, for the life of that one trip.
"""
from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.logging import logger
from app.core.rate_limit import limiter
from app.models.enums import TripStatus
from app.models.notifications import TripSubscription
from app.models.organizations import Organization
from app.models.trips import Trip
from app.models.trucks import Truck, TruckLocation
from app.services import eta as eta_service
from app.services import geocoding
from app.services.telegram import stage_label

router = APIRouter(prefix="/api/track", tags=["Public tracking"])

# Trips a customer can still be shown live. A delivered or cancelled load has
# nothing left to watch, and leaving the page live afterwards would keep the
# fleet's lorry visible to a stranger long after the job it was shared for.
# ``planned`` counts once a lorry is booked: the customer wants to see it coming
# to load, and dispatchers share the link the moment the job is set up.
_WATCHABLE = {TripStatus.planned, TripStatus.loading, TripStatus.en_route, TripStatus.at_border}
# Not live yet, but will be. Answered apart from "invalid" so the page can tell
# the customer to wait instead of sending them back for a link that would fail
# the same way. Only reachable with a real token, so it reveals nothing to a
# guesser that the token's 32 random characters do not already protect.
_NOT_STARTED = {TripStatus.draft, TripStatus.planned}


class TrackPoint(BaseModel):
    """Where the lorry is, and how fresh that is."""

    latitude: float
    longitude: float
    speed: float
    heading: float | None = None
    place: str | None = None
    recorded_at: datetime


class TrackPlace(BaseModel):
    """A named end of the route, with coordinates when we have them."""

    name: str | None = None
    latitude: float | None = None
    longitude: float | None = None


class TrackOut(BaseModel):
    """Everything the public page renders. Nothing else leaves the server."""

    org_name: str
    reference: str
    cargo: str | None = None
    plate: str | None = None
    stage: str | None = None
    loaded_at: datetime | None = None
    # A calendar date, not a timestamp. Sent as a timestamp it arrived at UTC
    # midnight and, rendered in a timezone behind UTC, showed the day before —
    # a delivery date that is wrong by a day is worse than none at all.
    eta_customs: date | None = None
    eta_is_measured: bool = False
    origin: TrackPlace
    destination: TrackPlace
    position: TrackPoint | None = None


async def _subscription_or_404(db: AsyncSession, token: str) -> TripSubscription:
    # A wrong token and a token for a finished trip both answer 404 with the
    # same wording: distinguishing them tells a guesser which of their guesses
    # was a real subscription.
    sub = (
        await db.execute(select(TripSubscription).where(TripSubscription.token == token))
    ).scalar_one_or_none()
    if sub is None:
        raise HTTPException(status_code=404, detail="Ссылка недействительна")
    return sub


@router.get("/{token}", response_model=TrackOut)
@limiter.limit("60/minute")
async def track(
    request: Request,  # noqa: ARG001 — slowapi reads the client address off it
    token: str,
    db: AsyncSession = Depends(get_db),
) -> TrackOut:
    """One trip's live position, for whoever holds the link."""
    sub = await _subscription_or_404(db, token)

    trip = (await db.execute(select(Trip).where(Trip.id == sub.trip_id))).scalar_one_or_none()
    if trip is None:
        raise HTTPException(status_code=404, detail="Ссылка недействительна")
    live = trip.status in _WATCHABLE and not (
        trip.status == TripStatus.planned and trip.truck_id is None
    )
    if not live:
        if trip.status in _NOT_STARTED:
            raise HTTPException(status_code=409, detail="not_started")
        raise HTTPException(status_code=404, detail="Ссылка недействительна")

    org_name = (
        await db.execute(select(Organization.name).where(Organization.id == trip.org_id))
    ).scalar_one_or_none() or "—"

    plate: str | None = None
    position: TrackPoint | None = None
    if trip.truck_id is not None:
        truck = (
            await db.execute(select(Truck).where(Truck.id == trip.truck_id))
        ).scalar_one_or_none()
        plate = truck.plate_number if truck else None

        loc = (
            await db.execute(
                select(TruckLocation).where(TruckLocation.truck_id == trip.truck_id)
            )
        ).scalar_one_or_none()
        if loc is not None:
            lat, lng = float(loc.latitude), float(loc.longitude)
            position = TrackPoint(
                latitude=lat,
                longitude=lng,
                speed=float(loc.speed),
                heading=float(loc.heading) if loc.heading is not None else None,
                # Same words as the Telegram card, from the same cached
                # geocoder: a customer comparing the page to the message they
                # got this morning should not have to reconcile two namings of
                # one place.
                place=loc.address or await geocoding.describe(lat, lng),
                recorded_at=loc.recorded_at,
            )

    estimate = None
    try:
        estimate = await eta_service.estimate_customs_arrival(
            db,
            trip,
            current_lat=position.latitude if position else None,
            current_lng=position.longitude if position else None,
            covered_km=_covered_km(trip, position),
        )
    except Exception:  # noqa: BLE001 — an estimate is never worth a blank page
        logger.exception("track_eta_failed", trip_id=str(trip.id))

    return TrackOut(
        org_name=org_name,
        reference=trip.reference,
        cargo=trip.cargo_description,
        plate=plate,
        stage=stage_label(trip.current_stage, trip.current_stage_place)
        if trip.current_stage
        else None,
        loaded_at=trip.loaded_at,
        eta_customs=estimate.day if estimate else None,
        eta_is_measured=bool(estimate and estimate.is_measured),
        origin=TrackPlace(
            name=trip.origin_name,
            latitude=float(trip.origin_lat) if trip.origin_lat is not None else None,
            longitude=float(trip.origin_lng) if trip.origin_lng is not None else None,
        ),
        destination=TrackPlace(
            name=trip.destination_name,
            latitude=float(trip.destination_lat) if trip.destination_lat is not None else None,
            longitude=float(trip.destination_lng) if trip.destination_lng is not None else None,
        ),
        position=position,
    )


def _covered_km(trip: Trip, position: TrackPoint | None) -> float:
    """Distance made good from the origin — what the estimate is paced against."""
    if position is None or trip.origin_lat is None or trip.origin_lng is None:
        return 0.0
    return eta_service.road_km(
        float(trip.origin_lat), float(trip.origin_lng), position.latitude, position.longitude
    )
