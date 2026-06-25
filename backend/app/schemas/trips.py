from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.models.enums import TripStatus, TripEventType, SegmentKind


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
    """Move a trip to a new status, logging a timeline event."""
    to_status: TripStatus
    note: Optional[str] = None
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)


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
