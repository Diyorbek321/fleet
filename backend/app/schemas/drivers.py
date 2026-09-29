from __future__ import annotations
import re

from pydantic import AliasChoices, BaseModel, Field, field_validator
from typing import Optional, List
from datetime import datetime, date
import uuid
from app.models.enums import DriverStatus

class DriverCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    phone: Optional[str] = Field(default=None, max_length=20)
    phone2: Optional[str] = Field(default=None, max_length=20)
    phone3: Optional[str] = Field(default=None, max_length=20)
    adr: bool = False
    passport_number: Optional[str] = Field(default=None, max_length=20)
    license_number: Optional[str] = Field(default=None, max_length=50)
    status: Optional[DriverStatus] = DriverStatus.active
    photo_url: Optional[str] = Field(default=None, max_length=500)

class DriverUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    phone: Optional[str] = Field(default=None, max_length=20)
    phone2: Optional[str] = Field(default=None, max_length=20)
    phone3: Optional[str] = Field(default=None, max_length=20)
    adr: Optional[bool] = None
    passport_number: Optional[str] = Field(default=None, max_length=20)
    license_number: Optional[str] = Field(default=None, max_length=50)
    status: Optional[DriverStatus] = None
    photo_url: Optional[str] = Field(default=None, max_length=500)

class DriverOut(BaseModel):
    id: uuid.UUID
    name: str
    phone: Optional[str]
    # ``email`` and ``license_expiry`` below are still returned although the
    # panel no longer asks for either: drivers entered before this change have
    # them filled in, and a field that stops being collected is not a reason to
    # stop showing what is already there.
    phone2: Optional[str] = None
    phone3: Optional[str] = None
    adr: bool = False
    email: Optional[str]
    passport_number: Optional[str] = None
    license_number: Optional[str] = None
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

# Latin letters and digits, with the separators a plate or an email carries.
# No spaces: "10 422 TCA" typed on a phone comes back as three different
# strings depending on the keyboard, so the login is the plate without them.
_LOGIN_RE = re.compile(r"^[a-z0-9][a-z0-9._@+-]{2,63}$")


class CreateDriverLoginIn(BaseModel):
    """Set — or reset — the login a driver signs into the app with.

    ``email`` is still accepted as the field name for callers built before the
    login stopped having to be an address.
    """
    login: str = Field(validation_alias=AliasChoices("login", "email"))
    password: str = Field(min_length=8, max_length=128)

    @field_validator("login")
    @classmethod
    def _normalise_login(cls, v: str) -> str:
        v = v.strip().lower()
        if not _LOGIN_RE.fullmatch(v):
            raise ValueError(
                "Логин: 3–64 символа — латинские буквы, цифры, точка, дефис, без пробелов"
            )
        return v


class DriverLoginOut(BaseModel):
    user_id: uuid.UUID
    driver_id: uuid.UUID
    login: str
    # The same value; kept for clients that read the old field name.
    email: str


class DriverLoginStatusOut(BaseModel):
    login: Optional[str] = None
