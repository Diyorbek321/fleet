from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime, date
import uuid
from app.models.enums import ServiceType, ServiceStatus

class MaintenanceRecordCreate(BaseModel):
    service_type: ServiceType
    description: Optional[str] = None
    cost: Optional[float] = Field(default=None, ge=0)
    mileage_at_service: Optional[float] = Field(default=None, ge=0)
    performed_by: Optional[str] = Field(default=None, max_length=100)
    performed_at: date
    notes: Optional[str] = None

class MaintenanceRecordUpdate(BaseModel):
    description: Optional[str] = None
    cost: Optional[float] = Field(default=None, ge=0)
    mileage_at_service: Optional[float] = Field(default=None, ge=0)
    performed_by: Optional[str] = Field(default=None, max_length=100)
    performed_at: Optional[date] = None
    notes: Optional[str] = None

class MaintenanceRecordOut(BaseModel):
    id: uuid.UUID
    truck_id: uuid.UUID
    service_type: ServiceType
    description: Optional[str]
    cost: Optional[float]
    mileage_at_service: Optional[float]
    performed_by: Optional[str]
    performed_at: date
    notes: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True

class FuelLogCreate(BaseModel):
    liters: float = Field(gt=0)
    cost_per_liter: float = Field(gt=0)
    total_cost: Optional[float] = Field(default=None, gt=0)
    mileage_at_fill: Optional[float] = Field(default=None, ge=0)
    fuel_station: Optional[str] = Field(default=None, max_length=200)
    filled_at: Optional[datetime] = None
    trip_id: Optional[uuid.UUID] = None

class FuelLogOut(BaseModel):
    id: uuid.UUID
    truck_id: uuid.UUID
    trip_id: Optional[uuid.UUID] = None
    liters: float
    cost_per_liter: float
    total_cost: float
    mileage_at_fill: Optional[float]
    fuel_station: Optional[str]
    filled_at: datetime
    created_at: datetime

    class Config:
        from_attributes = True

class ServiceIntervalOut(BaseModel):
    id: uuid.UUID
    truck_id: uuid.UUID
    service_type: ServiceType
    interval_km: Optional[float]
    interval_days: Optional[int]
    last_service_date: Optional[date]
    last_service_mileage: Optional[float]
    next_service_date: Optional[date]
    next_service_mileage: Optional[float]
    status: ServiceStatus

    class Config:
        from_attributes = True
