from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime, date
import uuid
from app.models.enums import TruckStatus

class TruckCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    plate_number: str = Field(min_length=1, max_length=20)
    model: Optional[str] = None
    year: Optional[int] = Field(default=None, ge=1900, le=2100)

class TruckUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    plate_number: Optional[str] = Field(default=None, min_length=1, max_length=20)
    model: Optional[str] = None
    year: Optional[int] = Field(default=None, ge=1900, le=2100)
    status: Optional[TruckStatus] = None
    fuel_level: Optional[float] = Field(default=None, ge=0, le=100)
    mileage: Optional[float] = Field(default=None, ge=0)

class TruckOut(BaseModel):
    id: uuid.UUID
    name: str
    plate_number: str
    model: Optional[str]
    year: Optional[int]
    status: TruckStatus
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
