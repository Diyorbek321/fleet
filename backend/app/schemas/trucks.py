from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime, date
import uuid
from app.models.enums import TrailerVolume, TruckStatus

class TruckCreate(BaseModel):
    # Optional: the form asks for the plate only, and the router names the
    # truck after it so no screen that prints a name prints a blank.
    name: Optional[str] = Field(default=None, max_length=100)
    plate_number: str = Field(min_length=1, max_length=20)
    model: Optional[str] = None
    year: Optional[int] = Field(default=None, ge=1900, le=2100)
    tractor_brand: Optional[str] = Field(default=None, max_length=60)
    trailer_brand: Optional[str] = Field(default=None, max_length=60)
    trailer_volume: Optional[TrailerVolume] = None
    insurance_expiry: Optional[date] = None

class TruckUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    plate_number: Optional[str] = Field(default=None, min_length=1, max_length=20)
    model: Optional[str] = None
    year: Optional[int] = Field(default=None, ge=1900, le=2100)
    tractor_brand: Optional[str] = Field(default=None, max_length=60)
    trailer_brand: Optional[str] = Field(default=None, max_length=60)
    trailer_volume: Optional[TrailerVolume] = None
    insurance_expiry: Optional[date] = None
    status: Optional[TruckStatus] = None
    # The dispatcher's switch, independent of `status`: a truck can be in
    # service and out of coverage at the same time.
    is_enabled: Optional[bool] = None
    fuel_level: Optional[float] = Field(default=None, ge=0, le=100)
    mileage: Optional[float] = Field(default=None, ge=0)

class TruckOut(BaseModel):
    id: uuid.UUID
    name: str
    plate_number: str
    model: Optional[str]
    year: Optional[int]
    tractor_brand: Optional[str] = None
    trailer_brand: Optional[str] = None
    trailer_volume: Optional[TrailerVolume] = None
    insurance_expiry: Optional[date] = None
    status: TruckStatus
    gps_disabled_at: Optional[datetime] = None
    is_enabled: bool
    fuel_level: float
    mileage: float
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class TruckLocationOut(BaseModel):
    truck_id: uuid.UUID
    latitude: float
    longitude: float
    speed: float
    heading: Optional[float]
    address: Optional[str]
    recorded_at: datetime

    class Config:
        from_attributes = True

class TruckDetailsOut(TruckOut):
    location: Optional[TruckLocationOut] = None
    driver: Optional[dict] = None  # compact driver info

class LocationHistoryItem(BaseModel):
    latitude: float
    longitude: float
    speed: Optional[float] = None
    heading: Optional[float] = None
    recorded_at: datetime

    class Config:
        from_attributes = True
