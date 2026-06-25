from __future__ import annotations

from datetime import datetime
from typing import Optional
import uuid

from pydantic import BaseModel, Field

from app.models.enums import GeofenceEventType


class GeofenceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    category: Optional[str] = Field(default=None, max_length=40)
    center_lat: float = Field(ge=-90, le=90)
    center_lng: float = Field(ge=-180, le=180)
    radius_m: float = Field(gt=0, le=1_000_000)
    active: bool = True


class GeofenceUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    category: Optional[str] = Field(default=None, max_length=40)
    center_lat: Optional[float] = Field(default=None, ge=-90, le=90)
    center_lng: Optional[float] = Field(default=None, ge=-180, le=180)
    radius_m: Optional[float] = Field(default=None, gt=0, le=1_000_000)
    active: Optional[bool] = None


class GeofenceOut(BaseModel):
    id: uuid.UUID
    name: str
    category: Optional[str]
    center_lat: float
    center_lng: float
    radius_m: float
    active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class GeofenceEventOut(BaseModel):
    id: uuid.UUID
    geofence_id: uuid.UUID
    truck_id: uuid.UUID
    event: GeofenceEventType
    latitude: float
    longitude: float
    recorded_at: datetime

    class Config:
        from_attributes = True
