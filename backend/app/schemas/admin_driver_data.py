"""Admin-facing views of data drivers submit from the mobile app.

These mirror the driver self-scoped schemas in ``schemas/me.py`` but add the
context an admin/manager needs (which driver, which truck) so the web app can
show a fleet-wide picture.
"""
from __future__ import annotations

import uuid
from datetime import datetime, date
from typing import Optional

from pydantic import BaseModel

from app.models.enums import ShiftStatus, MaintenanceRequestStatus, ExpenseCategory


class MaintenanceRequestAdminOut(BaseModel):
    id: uuid.UUID
    driver_id: Optional[uuid.UUID]
    driver_name: Optional[str]
    truck_id: Optional[uuid.UUID]
    truck_plate: Optional[str]
    title: str
    description: Optional[str]
    photo_url: Optional[str]
    status: MaintenanceRequestStatus
    created_at: datetime


class UpdateMaintenanceRequestStatusIn(BaseModel):
    status: MaintenanceRequestStatus


class ExpenseAdminOut(BaseModel):
    id: uuid.UUID
    driver_id: uuid.UUID
    truck_id: Optional[uuid.UUID]
    truck_plate: Optional[str]
    category: ExpenseCategory
    amount: float
    note: Optional[str]
    receipt_url: Optional[str]
    spent_at: date
    created_at: datetime


class ShiftAdminOut(BaseModel):
    id: uuid.UUID
    driver_id: uuid.UUID
    truck_id: Optional[uuid.UUID]
    truck_plate: Optional[str]
    status: ShiftStatus
    started_at: datetime
    ended_at: Optional[datetime]
    start_mileage: Optional[float]
    end_mileage: Optional[float]
