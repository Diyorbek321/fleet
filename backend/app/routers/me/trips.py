"""The driver's own trips: status timeline, document photos, expense report.

Everything here goes through :func:`own_trip_or_404`, so a driver can only
touch trips assigned to them.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Body,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.deps.auth import get_current_driver
from app.models.drivers import Driver
from app.models.enums import TripEventType, TripReportStatus, TripStatus
from app.models.trips import Trip, TripDocument, TripEvent
from app.routers.me._common import PREFIX, TAGS, own_trip_or_404
from app.schemas.trip_reports import TripExpenseReportIn, TripExpenseReportOut
from app.schemas.trips import TripAdvance, TripDocumentOut, TripOut
from app.services.storage import is_configured, presigned_get_url, put_object
from app.services.trip_notifications import notify_trip_status_change_background
from app.services.trip_reports import build_report_out, get_report, upsert_report

router = APIRouter(prefix=PREFIX, tags=TAGS)

_DRIVER_START_STATUSES = {TripStatus.en_route, TripStatus.loading}

# Cap a single upload at 10MB; phone photos are well under this.
_MAX_DOC_BYTES = 10 * 1024 * 1024
_DOC_EXT_BY_TYPE = {
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/heic": "heic",
    "image/heif": "heif",
    "image/gif": "gif",
}


def _doc_out(doc: TripDocument, *, driver_name: Optional[str] = None) -> TripDocumentOut:
    """Serialize a document with a freshly minted presigned read URL."""
    return TripDocumentOut(
        id=doc.id,
        trip_id=doc.trip_id,
        category=doc.category,
        caption=doc.caption,
        content_type=doc.content_type,
        size_bytes=doc.size_bytes,
        url=presigned_get_url(doc.storage_key),
        uploaded_at=doc.uploaded_at,
        driver_name=driver_name,
    )


# ── Trips (driver-scoped) ─────────────────────────────────────────────

@router.get("/trips", response_model=list[TripOut])
async def my_trips(
    driver: Driver = Depends(get_current_driver),
    db: AsyncSession = Depends(get_db),
):
    """My assigned trips, active ones first, newest first within each group."""
    res = await db.execute(
        select(Trip).where(Trip.driver_id == driver.id).order_by(desc(Trip.created_at))
    )
    trips = res.scalars().all()
    terminal = {TripStatus.delivered, TripStatus.cancelled}
    trips.sort(key=lambda tr: (tr.status in terminal, ))  # stable: active before terminal
    return trips


@router.post("/trips/{trip_id}/advance", response_model=TripOut)
async def advance_my_trip(
    trip_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    data: TripAdvance = Body(...),
    driver: Driver = Depends(get_current_driver),
    db: AsyncSession = Depends(get_db),
):
    """Advance one of my own trips and log a timeline event.

    Scoped to the signed-in driver — a driver can only move trips assigned to
    them. The optional lat/lng pins where the status change happened (e.g. the
    exact border arrival point), which feeds the leakage / dwell analytics.
    """
    trip = await own_trip_or_404(db, trip_id, driver)

    from_status = trip.status
    now = datetime.now(timezone.utc)
    if data.to_status in _DRIVER_START_STATUSES and trip.started_at is None:
        trip.started_at = now
    if data.to_status == TripStatus.delivered:
        trip.delivered_at = now
    trip.status = data.to_status
    trip.updated_at = now

    event_type = TripEventType.status_change
    if data.to_status == TripStatus.at_border:
        event_type = TripEventType.border_arrival
    elif data.to_status == TripStatus.delivered:
        event_type = TripEventType.pod

    db.add(
        TripEvent(
            trip_id=trip.id,
            event=event_type,
            from_status=from_status,
            to_status=data.to_status,
            note=data.note,
            latitude=data.latitude,
            longitude=data.longitude,
            recorded_at=now,
        )
    )
    await db.commit()

    # Notify cargo-owner subscribers over Telegram in the background — the
    # driver app must get its response immediately, not wait on Telegram.
    if from_status != data.to_status:
        background_tasks.add_task(
            notify_trip_status_change_background,
            trip.id,
            data.to_status,
            data.latitude,
            data.longitude,
            data.note,
        )

    return trip


# ── Trip documents (driver uploads photos, strictly per-trip) ──────────

@router.post(
    "/trips/{trip_id}/documents",
    response_model=TripDocumentOut,
    status_code=status.HTTP_201_CREATED,
)
async def upload_my_trip_document(
    trip_id: uuid.UUID,
    file: UploadFile = File(...),
    category: Optional[str] = Form(None),
    caption: Optional[str] = Form(None),
    driver: Driver = Depends(get_current_driver),
    db: AsyncSession = Depends(get_db),
):
    """Upload a document photo for one of my own trips.

    Strictly per-trip: the file is keyed under the trip and linked to its
    ``trip_id``/``org_id``, never shared across trips.
    """
    if not is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Document storage is not configured",
        )

    trip = await own_trip_or_404(db, trip_id, driver)

    content_type = (file.content_type or "").lower()
    if not content_type.startswith("image/"):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Only image uploads are allowed",
        )

    data = await file.read()
    if len(data) > _MAX_DOC_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="File too large (max 10MB)",
        )

    ext = _DOC_EXT_BY_TYPE.get(content_type, "bin")
    key = f"orgs/{trip.org_id}/trips/{trip.id}/{uuid.uuid4()}.{ext}"
    put_object(key, data, content_type)

    doc = TripDocument(
        org_id=trip.org_id,
        trip_id=trip.id,
        driver_id=driver.id,
        storage_key=key,
        content_type=content_type,
        size_bytes=len(data),
        category=category,
        caption=caption,
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)
    return _doc_out(doc, driver_name=driver.name)


@router.get("/trips/{trip_id}/documents", response_model=list[TripDocumentOut])
async def list_my_trip_documents(
    trip_id: uuid.UUID,
    driver: Driver = Depends(get_current_driver),
    db: AsyncSession = Depends(get_db),
):
    """My own trip's documents, newest first (presigned URLs)."""
    await own_trip_or_404(db, trip_id, driver)
    if not is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Document storage is not configured",
        )
    res = await db.execute(
        select(TripDocument)
        .where(TripDocument.trip_id == trip_id)
        .order_by(desc(TripDocument.uploaded_at))
    )
    docs = res.scalars().all()
    return [_doc_out(d, driver_name=driver.name) for d in docs]


# ── Trip expense report ("yo'l varaqasi") — driver-filled, self-scoped ──

@router.get("/trips/{trip_id}/report", response_model=Optional[TripExpenseReportOut])
async def my_trip_report(
    trip_id: uuid.UUID,
    driver: Driver = Depends(get_current_driver),
    db: AsyncSession = Depends(get_db),
):
    """My current draft/submitted report for this trip, or null if not started."""
    await own_trip_or_404(db, trip_id, driver)
    report = await get_report(db, trip_id)
    return build_report_out(report) if report else None


@router.put("/trips/{trip_id}/report", response_model=TripExpenseReportOut)
async def save_my_trip_report(
    trip_id: uuid.UUID,
    data: TripExpenseReportIn = Body(...),
    driver: Driver = Depends(get_current_driver),
    db: AsyncSession = Depends(get_db),
):
    """Save the whole report in one call — creates it on first save."""
    trip = await own_trip_or_404(db, trip_id, driver)
    report = await upsert_report(db, trip.id, trip.org_id, data)
    return build_report_out(report)


@router.post("/trips/{trip_id}/report/submit", response_model=TripExpenseReportOut)
async def submit_my_trip_report(
    trip_id: uuid.UUID,
    driver: Driver = Depends(get_current_driver),
    db: AsyncSession = Depends(get_db),
):
    """Mark the report submitted. Stays editable afterwards — this only flags
    the dispatcher that the driver considers it complete.
    """
    await own_trip_or_404(db, trip_id, driver)
    report = await get_report(db, trip_id)
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not started")
    report.status = TripReportStatus.submitted
    report.submitted_at = datetime.now(timezone.utc)
    await db.commit()
    return build_report_out(report)
