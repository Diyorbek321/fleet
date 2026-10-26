"""Which driver app version the server expects.

APKs are handed to drivers by hand, so phones keep running whatever they were
given — a build without the standing-still heartbeat made parked trucks look
dead for weeks. The app asks this on start and, when it is older than the
minimum, shows only an "update" screen with the download link.

Public on purpose: an app too old to sign in must still be able to ask.
"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.config import settings

router = APIRouter(prefix="/api/app", tags=["Driver App"])


class DriverVersionOut(BaseModel):
    min_version: str
    latest_version: str
    download_url: str


@router.get("/driver-version", response_model=DriverVersionOut)
async def driver_version() -> DriverVersionOut:
    return DriverVersionOut(
        min_version=settings.driver_app_min_version,
        latest_version=settings.driver_app_latest_version,
        download_url=settings.driver_app_download_url,
    )
