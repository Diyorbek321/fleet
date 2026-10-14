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
from app.core.logging import logger
from app.services.russia_stay_records import record_crossing
from app.deps.auth import get_current_driver
from app.models.drivers import Driver
from app.models.enums import (
    STAGE_TO_STATUS,
    TripEventType,
    TripReportStatus,
    TripStage,
    TripStatus,
)
from app.models.trips import Trip, TripDocument, TripEvent
from app.routers.me._common import PREFIX, TAGS, own_trip_or_404
from app.schemas.trip_reports import TripExpenseReportIn, TripExpenseReportOut
from app.schemas.trips import TripAdvance, TripDocumentOut, TripDocumentUpdate, TripOut
from app.services.storage import delete_object, is_configured, presigned_get_url, put_object
from app.services.trip_notifications import notify_trip_status_change_background
from app.services.trip_reports import build_report_out, get_report, upsert_report

router = APIRouter(prefix=PREFIX, tags=TAGS)

_DRIVER_START_STATUSES = {TripStatus.en_route, TripStatus.loading}

# The checkpoint that means "the load is on board" — what the cargo owner's
# card calls the loading date. Reported once; a driver who taps it twice after
# a reload does not move the date the customer was already given.
_LOADED_STAGE = TripStage.loaded_waiting_docs

# Cap a single upload at 10MB; phone photos are well under this.
_MAX_DOC_BYTES = 10 * 1024 * 1024
# The formats a driver's phone actually produces, mapped to the extension the
# file is stored under. The extension is not cosmetic: /api/files derives the
# Content-Type it serves from it, so a type absent from this map used to be
# stored as `.bin`, accepted with a 201, and then served as an undisplayable
# download — an upload that looked successful and left the trip without its
# document.
_DOC_EXT_BY_TYPE = {
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/heic": "heic",
    "image/heif": "heif",
    "image/gif": "gif",
}

# Membership of the map above IS the allowlist. The previous check accepted any
# `image/*`, which let `image/svg+xml` — a scriptable document, not a picture —
# through the door on its way to a `.bin` file nobody could open.
ALLOWED_DOC_CONTENT_TYPES = frozenset(_DOC_EXT_BY_TYPE)


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

    # A driver reports a checkpoint; the coarse status is derived from it, so
    # the panel, the alerts and the margin keep reading the one field they
    # always read. A dispatcher sending a bare status still works.
    to_status = STAGE_TO_STATUS[data.stage] if data.stage else data.to_status
    assert to_status is not None  # TripAdvance rejects the empty body

    if to_status in _DRIVER_START_STATUSES and trip.started_at is None:
        trip.started_at = now
    if to_status == TripStatus.delivered:
        trip.delivered_at = now
    if data.stage is _LOADED_STAGE and trip.loaded_at is None:
        trip.loaded_at = now
    if data.stage is not None:
        trip.current_stage = data.stage
        trip.current_stage_place = data.stage_place
    trip.status = to_status
    trip.updated_at = now

    event_type = TripEventType.status_change
    if data.stage is TripStage.crossed_border:
        event_type = TripEventType.border_clear
    elif to_status == TripStatus.at_border:
        event_type = TripEventType.border_arrival
    elif to_status == TripStatus.delivered:
        event_type = TripEventType.pod

    db.add(
        TripEvent(
            trip_id=trip.id,
            event=event_type,
            from_status=from_status,
            to_status=to_status,
            stage=data.stage,
            stage_place=data.stage_place,
            note=data.note,
            latitude=data.latitude,
            longitude=data.longitude,
            recorded_at=now,
        )
    )
    await record_crossing(db, trip, data.stage, data.stage_place, now)
    await db.commit()

    # Notify cargo-owner subscribers over Telegram in the background — the
    # driver app must get its response immediately, not wait on Telegram.
    #
    # Keyed on the stage, not the status: "прибыл на границу УЗБ–КЗ" and
    # "прошёл границу УЗБ–КЗ" are two things the customer wants to hear, and
    # both sit inside the same coarse status move.
    if data.stage is not None or from_status != to_status:
        background_tasks.add_task(
            notify_trip_status_change_background,
            trip.id,
            to_status,
            data.latitude,
            data.longitude,
            data.note,
        )

    return trip


# ── Trip documents (driver uploads photos, strictly per-trip) ──────────

async def _read_image(file: UploadFile) -> tuple[str, bytes]:
    """The upload's content type and bytes, or the 415/413 that refuses it."""
    # Strip any ";charset=..." the client tacked on before matching.
    content_type = (file.content_type or "").split(";")[0].strip().lower()
    if content_type not in ALLOWED_DOC_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=(
                "Неподдерживаемый тип изображения. Разрешены: "
                + ", ".join(sorted(ALLOWED_DOC_CONTENT_TYPES))
            ),
        )
    data = await file.read()
    if len(data) > _MAX_DOC_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Файл слишком большой (максимум 10 МБ)",
        )
    return content_type, data


def _store_image(trip: Trip, content_type: str, data: bytes) -> str:
    ext = _DOC_EXT_BY_TYPE[content_type]  # guaranteed by the allowlist in _read_image
    key = f"orgs/{trip.org_id}/trips/{trip.id}/{uuid.uuid4()}.{ext}"
    put_object(key, data, content_type)
    return key


def _discard_file(key: str) -> None:
    """Best effort: the row is already right, and a file left on disk is a
    smaller fault than answering 500 for a change that was saved."""
    try:
        delete_object(key)
    except Exception:  # noqa: BLE001
        logger.exception("trip_document_file_delete_failed", key=key)


def _require_storage() -> None:
    if not is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Хранилище документов не настроено",
        )


async def _my_editable_document(
    db: AsyncSession, trip_id: uuid.UUID, doc_id: uuid.UUID, driver: Driver
) -> tuple[Trip, TripDocument]:
    """A document this driver uploaded, on their own trip that is still running.

    Someone else's upload — the driver who had the trip before — is a 404, as
    is a document on someone else's trip. After delivery (or cancellation) the
    paperwork is what the trip was settled on: 409, and the desk changes it.
    """
    trip = await own_trip_or_404(db, trip_id, driver)
    doc = (
        await db.execute(
            select(TripDocument).where(
                TripDocument.id == doc_id,
                TripDocument.trip_id == trip.id,
                TripDocument.driver_id == driver.id,
            )
        )
    ).scalar_one_or_none()
    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Документ не найден")
    if trip.status in (TripStatus.delivered, TripStatus.cancelled):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Рейс закрыт — изменить документ может только диспетчер",
        )
    return trip, doc


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
            detail="Хранилище документов не настроено",
        )

    trip = await own_trip_or_404(db, trip_id, driver)
    content_type, data = await _read_image(file)
    key = _store_image(trip, content_type, data)

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
            detail="Хранилище документов не настроено",
        )
    res = await db.execute(
        select(TripDocument)
        .where(TripDocument.trip_id == trip_id)
        .order_by(desc(TripDocument.uploaded_at))
    )
    docs = res.scalars().all()
    return [_doc_out(d, driver_name=driver.name) for d in docs]


@router.patch("/trips/{trip_id}/documents/{doc_id}", response_model=TripDocumentOut)
async def update_my_trip_document(
    trip_id: uuid.UUID,
    doc_id: uuid.UUID,
    data: TripDocumentUpdate,
    driver: Driver = Depends(get_current_driver),
    db: AsyncSession = Depends(get_db),
):
    """Relabel one of my document photos (its category or note)."""
    _require_storage()
    _, doc = await _my_editable_document(db, trip_id, doc_id, driver)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(doc, field, value)
    await db.commit()
    return _doc_out(doc, driver_name=driver.name)


@router.put("/trips/{trip_id}/documents/{doc_id}/file", response_model=TripDocumentOut)
async def replace_my_trip_document_file(
    trip_id: uuid.UUID,
    doc_id: uuid.UUID,
    file: UploadFile = File(...),
    driver: Driver = Depends(get_current_driver),
    db: AsyncSession = Depends(get_db),
):
    """Retake a photo: the same document, a new picture, the old file removed."""
    _require_storage()
    trip, doc = await _my_editable_document(db, trip_id, doc_id, driver)
    content_type, data = await _read_image(file)
    old_key = doc.storage_key
    new_key = _store_image(trip, content_type, data)
    doc.storage_key = new_key
    doc.content_type = content_type
    doc.size_bytes = len(data)
    doc.uploaded_at = datetime.now(timezone.utc)
    try:
        await db.commit()
    except Exception:
        _discard_file(new_key)  # the row still points at the old photo
        raise
    # Only once the row points at the new file: a failed commit must not leave
    # the document pointing at nothing.
    _discard_file(old_key)
    return _doc_out(doc, driver_name=driver.name)


@router.delete("/trips/{trip_id}/documents/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_my_trip_document(
    trip_id: uuid.UUID,
    doc_id: uuid.UUID,
    driver: Driver = Depends(get_current_driver),
    db: AsyncSession = Depends(get_db),
):
    """Delete one of my document photos — the file as well as the row."""
    _require_storage()
    _, doc = await _my_editable_document(db, trip_id, doc_id, driver)
    key = doc.storage_key
    await db.delete(doc)
    await db.commit()
    _discard_file(key)


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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Отчёт ещё не начат")
    report.status = TripReportStatus.submitted
    report.submitted_at = datetime.now(timezone.utc)
    await db.commit()
    return build_report_out(report)
