from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class DriverMessageIn(BaseModel):
    """What a dispatcher types. The title is optional; the text is the message."""

    title: Optional[str] = Field(default=None, max_length=120)
    body: str = Field(min_length=1, max_length=1000)

    @field_validator("title", "body")
    @classmethod
    def _strip(cls, value: Optional[str]) -> Optional[str]:
        return value.strip() if value is not None else None

    @field_validator("body")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value:
            raise ValueError("Текст сообщения пуст")
        return value


class DriverMessageOut(BaseModel):
    id: uuid.UUID
    driver_id: uuid.UUID
    truck_id: Optional[uuid.UUID]
    kind: str
    title: str
    body: str
    devices_delivered: int
    created_at: datetime
    read_at: Optional[datetime]

    class Config:
        from_attributes = True


class GpsStatusIn(BaseModel):
    """The phone's own report of whether location services are on."""

    enabled: bool
