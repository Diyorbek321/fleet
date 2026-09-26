from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field, model_validator

from app.models.enums import (
    SegmentKind,
    StagePlace,
    TripEventType,
    TripStage,
    TripStatus,
    places_for_stage,
)


class TripCreate(BaseModel):
    reference: Optional[str] = Field(default=None, max_length=40)
    truck_id: Optional[uuid.UUID] = None
    driver_id: Optional[uuid.UUID] = None
    shipper: Optional[str] = Field(default=None, max_length=200)
    consignee: Optional[str] = Field(default=None, max_length=200)
    origin_name: Optional[str] = Field(default=None, max_length=200)
    origin_lat: Optional[float] = Field(default=None, ge=-90, le=90)
    origin_lng: Optional[float] = Field(default=None, ge=-180, le=180)
    destination_name: Optional[str] = Field(default=None, max_length=200)
    destination_lat: Optional[float] = Field(default=None, ge=-90, le=90)
    destination_lng: Optional[float] = Field(default=None, ge=-180, le=180)
    border_crossing: Optional[str] = Field(default=None, max_length=120)
    loading_address: Optional[str] = None
    loading_contact: Optional[str] = Field(default=None, max_length=200)
    customs_point: Optional[str] = Field(default=None, max_length=200)
    unloading_address: Optional[str] = None
    declarant_contact: Optional[str] = Field(default=None, max_length=200)
    cargo_description: Optional[str] = Field(default=None, max_length=255)
    cargo_weight_kg: Optional[float] = Field(default=None, ge=0)
    is_reefer: bool = False
    rate: float = Field(default=0, ge=0)
    currency: str = Field(default="UZS", min_length=3, max_length=3)
    planned_distance_km: Optional[float] = Field(default=None, ge=0)
    scheduled_start: Optional[datetime] = None
    scheduled_end: Optional[datetime] = None
    notes: Optional[str] = None


class TripUpdate(BaseModel):
    truck_id: Optional[uuid.UUID] = None
    driver_id: Optional[uuid.UUID] = None
    shipper: Optional[str] = Field(default=None, max_length=200)
    consignee: Optional[str] = Field(default=None, max_length=200)
    origin_name: Optional[str] = Field(default=None, max_length=200)
    origin_lat: Optional[float] = Field(default=None, ge=-90, le=90)
    origin_lng: Optional[float] = Field(default=None, ge=-180, le=180)
    destination_name: Optional[str] = Field(default=None, max_length=200)
    destination_lat: Optional[float] = Field(default=None, ge=-90, le=90)
    destination_lng: Optional[float] = Field(default=None, ge=-180, le=180)
    border_crossing: Optional[str] = Field(default=None, max_length=120)
    loading_address: Optional[str] = None
    loading_contact: Optional[str] = Field(default=None, max_length=200)
    customs_point: Optional[str] = Field(default=None, max_length=200)
    unloading_address: Optional[str] = None
    declarant_contact: Optional[str] = Field(default=None, max_length=200)
    cargo_description: Optional[str] = Field(default=None, max_length=255)
    cargo_weight_kg: Optional[float] = Field(default=None, ge=0)
    is_reefer: Optional[bool] = None
    rate: Optional[float] = Field(default=None, ge=0)
    currency: Optional[str] = Field(default=None, min_length=3, max_length=3)
    planned_distance_km: Optional[float] = Field(default=None, ge=0)
    scheduled_start: Optional[datetime] = None
    scheduled_end: Optional[datetime] = None
    notes: Optional[str] = None


class TripAdvance(BaseModel):
    """Move a trip on, logging a timeline event.

    Either form is accepted. A driver sends ``stage`` (+ ``stage_place``) and
    the server derives the status from it; the dispatcher panel still sends a
    bare ``to_status``, because from a desk "mark it delivered" is the whole
    intent and there is no checkpoint to report.
    """

    to_status: Optional[TripStatus] = None
    stage: Optional[TripStage] = None
    stage_place: Optional[StagePlace] = None
    note: Optional[str] = None
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)

    @model_validator(mode="after")
    def _one_of_stage_or_status(self) -> "TripAdvance":
        if self.stage is None and self.to_status is None:
            raise ValueError("Укажите stage или to_status")
        if self.stage is not None and self.stage_place is not None:
            allowed = places_for_stage(self.stage)
            if self.stage_place not in allowed:
                # A border stage carries a crossing, everything else a country.
                # Rejecting the mismatch here keeps the medians behind the
                # arrival estimate from pooling two different borders together.
                names = ", ".join(p.value for p in allowed)
                raise ValueError(f"Для этого этапа допустимо: {names}")
        return self


class TripEventOut(BaseModel):
    id: uuid.UUID
    event: TripEventType
    from_status: Optional[TripStatus]
    to_status: Optional[TripStatus]
    note: Optional[str]
    latitude: Optional[float]
    longitude: Optional[float]
    recorded_at: datetime

    class Config:
        from_attributes = True


class TripOut(BaseModel):
    id: uuid.UUID
    reference: str
    truck_id: Optional[uuid.UUID]
    driver_id: Optional[uuid.UUID]
    status: TripStatus
    shipper: Optional[str]
    consignee: Optional[str]
    origin_name: Optional[str]
    origin_lat: Optional[float]
    origin_lng: Optional[float]
    destination_name: Optional[str]
    destination_lat: Optional[float]
    destination_lng: Optional[float]
    border_crossing: Optional[str] = None
    loading_address: Optional[str] = None
    loading_contact: Optional[str] = None
    customs_point: Optional[str] = None
    unloading_address: Optional[str] = None
    declarant_contact: Optional[str] = None
    cargo_description: Optional[str]
    cargo_weight_kg: Optional[float]
    is_reefer: bool
    rate: float
    currency: str
    planned_distance_km: Optional[float]
    scheduled_start: Optional[datetime]
    scheduled_end: Optional[datetime]
    started_at: Optional[datetime]
    delivered_at: Optional[datetime]
    loaded_at: Optional[datetime] = None
    current_stage: Optional[TripStage] = None
    current_stage_place: Optional[StagePlace] = None
    # Filled by the trips router where it is worth a query; absent elsewhere,
    # because an estimate costs a scan of the corridor's history and a trip
    # list of forty rows does not need forty of them.
    eta_customs: Optional[date] = None
    eta_basis: Optional[str] = None
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class TripDetailsOut(TripOut):
    events: list[TripEventOut] = []
    truck_name: Optional[str] = None
    truck_plate: Optional[str] = None
    driver_name: Optional[str] = None


class TripSegmentOut(BaseModel):
    """A moving/stopped stretch of a trip computed from its GPS history."""
    id: uuid.UUID
    seq: int
    kind: SegmentKind
    started_at: datetime
    ended_at: datetime
    duration_s: int
    start_lat: Optional[float]
    start_lng: Optional[float]
    end_lat: Optional[float]
    end_lng: Optional[float]
    distance_km: float
    point_count: int

    class Config:
        from_attributes = True


class TripDocumentOut(BaseModel):
    """A driver-uploaded document for a trip.

    ``url`` is a short-lived presigned link built by the router at response time;
    it is not stored on the model.
    """
    id: uuid.UUID
    trip_id: uuid.UUID
    category: Optional[str] = None
    caption: Optional[str] = None
    content_type: Optional[str] = None
    size_bytes: Optional[int] = None
    url: str
    uploaded_at: datetime
    driver_name: Optional[str] = None

    class Config:
        from_attributes = True


class TripPnL(BaseModel):
    """Profit-and-loss for a single trip — the owner's money question."""
    trip_id: uuid.UUID
    reference: str
    status: TripStatus
    currency: str
    revenue: float
    fuel_cost: float
    expense_cost: float
    total_cost: float
    profit: float
    margin_pct: float
