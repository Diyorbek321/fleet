"""Schemas for the manager-facing CarGoRuqsat border-queue panel (`/api/queue`)."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class OrgQueueRowOut(BaseModel):
    """One driver's border-queue watch as shown on the manager panel."""

    watch_id: uuid.UUID
    driver_id: uuid.UUID
    driver_name: str
    plate: str
    checkpoint: str
    country: Optional[str]
    active: bool
    last_status: Optional[str]
    last_seen_queue_at: Optional[datetime]
    updated_at: datetime

    class Config:
        from_attributes = True
