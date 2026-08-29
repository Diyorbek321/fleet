"""Schemas for the self-scoped driver mobile app (`/api/me`)."""
from __future__ import annotations

import uuid
from datetime import datetime, date
from typing import Optional

from pydantic import BaseModel, Field

from app.models.enums import ShiftStatus, MaintenanceRequestStatus, ExpenseCategory


class AssignedTruckOut(BaseModel):
    id: uuid.UUID
    name: str
    plate_number: str
    model: Optional[str]
    status: str
    fuel_level: float
    mileage: float

    class Config:
        from_attributes = True


class ShiftStartIn(BaseModel):
    start_mileage: Optional[float] = Field(default=None, ge=0)


class ShiftEndIn(BaseModel):
    end_mileage: Optional[float] = Field(default=None, ge=0)


class ShiftOut(BaseModel):
    id: uuid.UUID
    driver_id: uuid.UUID
    truck_id: Optional[uuid.UUID]
    status: ShiftStatus
    started_at: datetime
    ended_at: Optional[datetime]
    start_mileage: Optional[float]
    end_mileage: Optional[float]

    class Config:
        from_attributes = True


class MaintenanceRequestCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: Optional[str] = None
    photo_url: Optional[str] = Field(default=None, max_length=500)


class MaintenanceRequestOut(BaseModel):
    id: uuid.UUID
    driver_id: Optional[uuid.UUID]
    truck_id: Optional[uuid.UUID]
    title: str
    description: Optional[str]
    photo_url: Optional[str]
    status: MaintenanceRequestStatus
    created_at: datetime

    class Config:
        from_attributes = True


class ExpenseCreate(BaseModel):
    category: ExpenseCategory = ExpenseCategory.other
    amount: float = Field(gt=0)
    note: Optional[str] = Field(default=None, max_length=2000)
    receipt_url: Optional[str] = Field(default=None, max_length=500)
    spent_at: Optional[date] = None


class ExpenseOut(BaseModel):
    id: uuid.UUID
    driver_id: uuid.UUID
    truck_id: Optional[uuid.UUID]
    category: ExpenseCategory
    amount: float
    note: Optional[str]
    receipt_url: Optional[str]
    spent_at: date
    created_at: datetime

    class Config:
        from_attributes = True


class PushTokenIn(BaseModel):
    token: str = Field(min_length=1, max_length=512)
    platform: Optional[str] = Field(default=None, max_length=20)


class LocationPingIn(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    speed: float = 0
    heading: Optional[float] = None
    recorded_at: Optional[datetime] = None


# ── CarGoRuqsat border-queue ──────────────────────────────────────────

class QueueStatusOut(BaseModel):
    """A booking as the registry currently shows it.

    ``queue_at``/``queue_until`` bound an hour-long slot the driver has to
    present within, so a client that shows only the start is telling them a
    deadline that may already have passed.
    """

    plate: str
    checkpoint: str
    queue_at: Optional[datetime]
    queue_until: Optional[datetime] = None
    status: str
    raw_status: str


class QueueWatchIn(BaseModel):
    checkpoint: str = Field(min_length=1, max_length=200)
    country: Optional[str] = Field(default=None, max_length=100)


class QueueWatchOut(BaseModel):
    id: uuid.UUID
    plate: str
    checkpoint: str
    country: Optional[str]
    active: bool
    last_status: Optional[str]
    last_seen_queue_at: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True


class QueueRefreshOut(BaseModel):
    status: Optional[QueueStatusOut]
    changed: bool


class QueueHandoffOut(BaseModel):
    url: str
