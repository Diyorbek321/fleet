from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class DeviceCreate(BaseModel):
    imei: str = Field(min_length=8, max_length=32)
    name: Optional[str] = Field(default=None, max_length=100)
    truck_id: Optional[uuid.UUID] = None


class DeviceUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=100)
    truck_id: Optional[uuid.UUID] = None


class DeviceOut(BaseModel):
    id: uuid.UUID
    imei: str
    name: Optional[str]
    truck_id: Optional[uuid.UUID]
    last_seen_at: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True


class DeviceCreated(DeviceOut):
    """Returned exactly once at enrollment — contains the plaintext API key."""

    api_key: str


class DeviceRotateKey(BaseModel):
    api_key: str
