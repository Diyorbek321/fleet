from __future__ import annotations
from pydantic import BaseModel, Field, EmailStr
from typing import Optional, List
from datetime import datetime, date
import uuid
from app.models.enums import DriverStatus

class DriverCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    phone: Optional[str] = Field(default=None, max_length=20)
    email: Optional[EmailStr] = None
    license_number: str = Field(min_length=1, max_length=50)
    license_expiry: Optional[date] = None
    status: Optional[DriverStatus] = DriverStatus.active
    photo_url: Optional[str] = Field(default=None, max_length=500)

class DriverUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    phone: Optional[str] = Field(default=None, max_length=20)
    email: Optional[EmailStr] = None
    license_number: Optional[str] = Field(default=None, min_length=1, max_length=50)
    license_expiry: Optional[date] = None
    status: Optional[DriverStatus] = None
    photo_url: Optional[str] = Field(default=None, max_length=500)

class DriverOut(BaseModel):
    id: uuid.UUID
    name: str
    phone: Optional[str]
    email: Optional[str]
    license_number: str
    license_expiry: Optional[date]
    status: DriverStatus
    photo_url: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class SafetyScoreOut(BaseModel):
    id: uuid.UUID
    score: int
    speeding_events: int
    harsh_braking: int
    harsh_acceleration: int
    idle_time_minutes: int
    period_start: date
    period_end: date
    calculated_at: datetime

    class Config:
        from_attributes = True

class AssignDriverIn(BaseModel):
    truck_id: uuid.UUID

class CreateDriverLoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)

class DriverLoginOut(BaseModel):
    user_id: uuid.UUID
    driver_id: uuid.UUID
    email: str
