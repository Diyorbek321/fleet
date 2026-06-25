from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import hash_password  # bcrypt; reused for API key hashing
from app.deps.auth import require_role
from app.models.devices import Device
from app.models.trucks import Truck
from app.models.users import User
from app.models.enums import UserRole
from app.schemas.devices import (
    DeviceCreate,
    DeviceCreated,
    DeviceOut,
    DeviceRotateKey,
    DeviceUpdate,
)

router = APIRouter(prefix="/api/devices", tags=["Devices"])


def _generate_api_key() -> str:
    # 32 bytes → 43 urlsafe chars, plenty of entropy, safe to pass in HTTP headers
    return secrets.token_urlsafe(32)


async def _get_owned_device(db: AsyncSession, device_id: uuid.UUID, org: uuid.UUID) -> Device:
    device = (
        await db.execute(select(Device).where(Device.id == device_id, Device.org_id == org))
    ).scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    return device


@router.get("", response_model=list[DeviceOut])
async def list_devices(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.manager)),
):
    res = await db.execute(
        select(Device).where(Device.org_id == user.org_id).order_by(Device.created_at.desc())
    )
    return list(res.scalars().all())


@router.post("", response_model=DeviceCreated, status_code=201)
async def enroll_device(
    data: DeviceCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin)),
):
    existing = (await db.execute(select(Device).where(Device.imei == data.imei))).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="Device with this IMEI is already enrolled")

    # A device may only be bound to a truck owned by the same organization.
    if data.truck_id is not None:
        truck = (
            await db.execute(select(Truck).where(Truck.id == data.truck_id, Truck.org_id == user.org_id))
        ).scalar_one_or_none()
        if not truck:
            raise HTTPException(status_code=404, detail="Truck not found")

    api_key = _generate_api_key()
    device = Device(
        org_id=user.org_id,
        imei=data.imei,
        name=data.name,
        truck_id=data.truck_id,
        api_key_hash=hash_password(api_key),
    )
    db.add(device)
    await db.commit()
    await db.refresh(device)

    return DeviceCreated(
        id=device.id,
        imei=device.imei,
        name=device.name,
        truck_id=device.truck_id,
        last_seen_at=device.last_seen_at,
        created_at=device.created_at,
        api_key=api_key,
    )


@router.put("/{device_id}", response_model=DeviceOut)
async def update_device(
    device_id: uuid.UUID,
    data: DeviceUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.manager)),
):
    device = await _get_owned_device(db, device_id, user.org_id)

    payload = data.model_dump(exclude_unset=True)
    # If re-binding to a truck, that truck must belong to the same org.
    if payload.get("truck_id") is not None:
        truck = (
            await db.execute(select(Truck).where(Truck.id == payload["truck_id"], Truck.org_id == user.org_id))
        ).scalar_one_or_none()
        if not truck:
            raise HTTPException(status_code=404, detail="Truck not found")

    for k, v in payload.items():
        setattr(device, k, v)

    await db.commit()
    await db.refresh(device)
    return device


@router.post("/{device_id}/rotate-key", response_model=DeviceRotateKey)
async def rotate_api_key(
    device_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin)),
):
    device = await _get_owned_device(db, device_id, user.org_id)

    api_key = _generate_api_key()
    device.api_key_hash = hash_password(api_key)
    await db.commit()
    return DeviceRotateKey(api_key=api_key)


@router.delete("/{device_id}", status_code=204)
async def delete_device(
    device_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin)),
):
    device = await _get_owned_device(db, device_id, user.org_id)
    await db.delete(device)
    await db.commit()
