"""Self-scoped endpoints for the driver mobile app.

Every endpoint here is strictly scoped to the authenticated driver via
``get_current_driver`` — a driver can only ever read or write their own data,
their assigned truck, and their own shifts/requests.
"""
from __future__ import annotations

from datetime import datetime, date, timezone
from typing import Optional
import uuid

from fastapi import APIRouter, BackgroundTasks, Body, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.ws import ws_manager
from app.deps.auth import get_current_driver, get_current_user
from app.models.drivers import Driver, DriverAssignment, SafetyScore
from app.models.driver_app import Shift, MaintenanceRequest, PushToken, QueueWatch, DriverExpense
from app.models.maintenance import FuelLog, MaintenanceRecord
from app.models.trucks import Truck
from app.models.users import User
from app.models.enums import ShiftStatus, MaintenanceRequestStatus, TripStatus, TripEventType, TripReportStatus
from app.models.trips import Trip, TripEvent, TripDocument
from app.schemas.drivers import DriverOut, SafetyScoreOut
from app.schemas.maintenance import FuelLogCreate, FuelLogOut, MaintenanceRecordOut
from app.schemas.trips import TripAdvance, TripDocumentOut, TripOut
from app.schemas.trip_reports import TripExpenseReportIn, TripExpenseReportOut
from app.schemas.me import (
    AssignedTruckOut,
    ExpenseCreate,
    ExpenseOut,
    LocationPingIn,
    MaintenanceRequestCreate,
    MaintenanceRequestOut,
    PushTokenIn,
    QueueHandoffOut,
    QueueRefreshOut,
    QueueStatusOut,
    QueueWatchIn,
    QueueWatchOut,
    ShiftEndIn,
    ShiftOut,
    ShiftStartIn,
)
from app.services.cgr import BookingRecord, CgrClient, build_booking_handoff_url, get_cgr_client
from app.services.gps import upsert_latest_location
from app.services.storage import is_configured, presigned_get_url, put_object
from app.services.queue import evaluate_watch, notify_queue_change
from app.services.trip_notifications import notify_trip_status_change_background
from app.services.trip_reports import build_report_out, get_report, upsert_report

router = APIRouter(prefix="/api/me", tags=["Driver App"])


async def _active_assignment(db: AsyncSession, driver_id: uuid.UUID) -> Optional[DriverAssignment]:
    res = await db.execute(
        select(DriverAssignment)
        .where(DriverAssignment.driver_id == driver_id, DriverAssignment.unassigned_at.is_(None))
        .order_by(desc(DriverAssignment.assigned_at))
    )
    return res.scalars().first()


async def _assigned_truck(db: AsyncSession, driver_id: uuid.UUID) -> Optional[Truck]:
    assignment = await _active_assignment(db, driver_id)
    if assignment is None:
        return None
    res = await db.execute(select(Truck).where(Truck.id == assignment.truck_id))
    return res.scalar_one_or_none()


async def _require_assigned_truck(db: AsyncSession, driver_id: uuid.UUID) -> Truck:
    truck = await _assigned_truck(db, driver_id)
    if truck is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="No truck currently assigned")
    return truck


# ── Profile & assignment ──────────────────────────────────────────────

@router.get("/profile", response_model=DriverOut)
async def my_profile(driver: Driver = Depends(get_current_driver)):
    return driver


@router.get("/assignment", response_model=Optional[AssignedTruckOut])
async def my_assignment(
    driver: Driver = Depends(get_current_driver),
    db: AsyncSession = Depends(get_db),
):
    """The truck assigned to me right now, or null if none."""
    return await _assigned_truck(db, driver.id)


@router.get("/safety-score", response_model=Optional[SafetyScoreOut])
async def my_safety_score(
    driver: Driver = Depends(get_current_driver),
    db: AsyncSession = Depends(get_db),
):
    res = await db.execute(
        select(SafetyScore)
        .where(SafetyScore.driver_id == driver.id)
        .order_by(desc(SafetyScore.calculated_at))
    )
    return res.scalars().first()


# ── Shifts (clock in / out) ───────────────────────────────────────────

@router.get("/shifts/current", response_model=Optional[ShiftOut])
async def current_shift(
    driver: Driver = Depends(get_current_driver),
    db: AsyncSession = Depends(get_db),
):
    res = await db.execute(
        select(Shift)
        .where(Shift.driver_id == driver.id, Shift.status == ShiftStatus.active)
        .order_by(desc(Shift.started_at))
    )
    return res.scalars().first()


@router.post("/shifts/start", response_model=ShiftOut, status_code=status.HTTP_201_CREATED)
async def start_shift(
    data: ShiftStartIn = Body(default_factory=ShiftStartIn),
    driver: Driver = Depends(get_current_driver),
    db: AsyncSession = Depends(get_db),
):
    existing = await db.execute(
        select(Shift).where(Shift.driver_id == driver.id, Shift.status == ShiftStatus.active)
    )
    if existing.scalars().first():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A shift is already active")

    truck = await _assigned_truck(db, driver.id)
    shift = Shift(
        driver_id=driver.id,
        truck_id=truck.id if truck else None,
        start_mileage=data.start_mileage,
    )
    db.add(shift)
    await db.commit()
    await db.refresh(shift)
    return shift


@router.post("/shifts/end", response_model=ShiftOut)
async def end_shift(
    data: ShiftEndIn = Body(default_factory=ShiftEndIn),
    driver: Driver = Depends(get_current_driver),
    db: AsyncSession = Depends(get_db),
):
    res = await db.execute(
        select(Shift)
        .where(Shift.driver_id == driver.id, Shift.status == ShiftStatus.active)
        .order_by(desc(Shift.started_at))
    )
    shift = res.scalars().first()
    if shift is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="No active shift")

    shift.status = ShiftStatus.ended
    shift.ended_at = datetime.now(timezone.utc)
    shift.end_mileage = data.end_mileage
    await db.commit()
    await db.refresh(shift)
    return shift


# ── Live location (phone-as-tracker) ──────────────────────────────────

@router.post("/location")
async def ping_location(
    data: LocationPingIn = Body(...),
    driver: Driver = Depends(get_current_driver),
    db: AsyncSession = Depends(get_db),
):
    """Driver's phone streams its GPS position to their assigned truck."""
    truck = await _require_assigned_truck(db, driver.id)
    await upsert_latest_location(
        db=db,
        truck_id=truck.id,
        latitude=data.latitude,
        longitude=data.longitude,
        speed=data.speed,
        heading=data.heading,
        recorded_at=data.recorded_at,
    )
    await db.commit()
    # Live map fan-out is scoped to the truck's organization.
    await ws_manager.broadcast_to_org(str(truck.org_id), {
        "type": "truck_location_update",
        "truck_id": str(truck.id),
        "lat": data.latitude,
        "lng": data.longitude,
        "speed": data.speed,
        "heading": data.heading,
        "recorded_at": (data.recorded_at or datetime.now(timezone.utc)).isoformat(),
    })
    return {"message": "ok", "truck_id": str(truck.id)}


# ── Fuel logs ─────────────────────────────────────────────────────────

@router.get("/fuel-logs", response_model=list[FuelLogOut])
async def my_fuel_logs(
    driver: Driver = Depends(get_current_driver),
    db: AsyncSession = Depends(get_db),
    limit: int = 50,
):
    truck = await _assigned_truck(db, driver.id)
    if truck is None:
        return []
    res = await db.execute(
        select(FuelLog)
        .where(FuelLog.truck_id == truck.id)
        .order_by(desc(FuelLog.filled_at))
        .limit(min(limit, 200))
    )
    return list(res.scalars().all())


@router.post("/fuel-logs", response_model=FuelLogOut, status_code=status.HTTP_201_CREATED)
async def add_fuel_log(
    data: FuelLogCreate = Body(...),
    driver: Driver = Depends(get_current_driver),
    db: AsyncSession = Depends(get_db),
):
    truck = await _require_assigned_truck(db, driver.id)
    total = data.total_cost if data.total_cost is not None else round(data.liters * data.cost_per_liter, 2)
    log = FuelLog(
        truck_id=truck.id,
        liters=data.liters,
        cost_per_liter=data.cost_per_liter,
        total_cost=total,
        mileage_at_fill=data.mileage_at_fill,
        fuel_station=data.fuel_station,
        filled_at=data.filled_at or datetime.now(timezone.utc),
    )
    db.add(log)
    await db.commit()
    await db.refresh(log)
    return log


# ── Daily expenses ────────────────────────────────────────────────────

@router.get("/expenses", response_model=list[ExpenseOut])
async def my_expenses(
    driver: Driver = Depends(get_current_driver),
    db: AsyncSession = Depends(get_db),
    month: Optional[str] = None,
    limit: int = 200,
):
    """My expenses, newest first. Optional ``month`` filter as ``YYYY-MM``."""
    stmt = select(DriverExpense).where(DriverExpense.driver_id == driver.id)
    if month:
        try:
            year_s, mon_s = month.split("-")
            start = date(int(year_s), int(mon_s), 1)
            end = date(start.year + (start.month == 12), (start.month % 12) + 1, 1)
        except (ValueError, IndexError):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="month must be YYYY-MM")
        stmt = stmt.where(DriverExpense.spent_at >= start, DriverExpense.spent_at < end)
    stmt = stmt.order_by(desc(DriverExpense.spent_at), desc(DriverExpense.created_at)).limit(min(limit, 500))
    res = await db.execute(stmt)
    return list(res.scalars().all())


@router.post("/expenses", response_model=ExpenseOut, status_code=status.HTTP_201_CREATED)
async def add_expense(
    data: ExpenseCreate = Body(...),
    driver: Driver = Depends(get_current_driver),
    db: AsyncSession = Depends(get_db),
):
    truck = await _assigned_truck(db, driver.id)
    expense = DriverExpense(
        driver_id=driver.id,
        truck_id=truck.id if truck else None,
        category=data.category,
        amount=data.amount,
        note=data.note,
        receipt_url=data.receipt_url,
        spent_at=data.spent_at or datetime.now(timezone.utc).date(),
    )
    db.add(expense)
    await db.commit()
    await db.refresh(expense)
    return expense


@router.delete("/expenses/{expense_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_expense(
    expense_id: uuid.UUID,
    driver: Driver = Depends(get_current_driver),
    db: AsyncSession = Depends(get_db),
):
    res = await db.execute(
        select(DriverExpense).where(
            DriverExpense.id == expense_id, DriverExpense.driver_id == driver.id
        )
    )
    expense = res.scalar_one_or_none()
    if expense is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Expense not found")
    await db.delete(expense)
    await db.commit()


# ── Maintenance: view records & report issues ─────────────────────────

@router.get("/maintenance", response_model=list[MaintenanceRecordOut])
async def my_truck_maintenance(
    driver: Driver = Depends(get_current_driver),
    db: AsyncSession = Depends(get_db),
):
    truck = await _assigned_truck(db, driver.id)
    if truck is None:
        return []
    res = await db.execute(
        select(MaintenanceRecord)
        .where(MaintenanceRecord.truck_id == truck.id)
        .order_by(desc(MaintenanceRecord.performed_at))
    )
    return list(res.scalars().all())


@router.get("/maintenance-requests", response_model=list[MaintenanceRequestOut])
async def my_maintenance_requests(
    driver: Driver = Depends(get_current_driver),
    db: AsyncSession = Depends(get_db),
):
    res = await db.execute(
        select(MaintenanceRequest)
        .where(MaintenanceRequest.driver_id == driver.id)
        .order_by(desc(MaintenanceRequest.created_at))
    )
    return list(res.scalars().all())


@router.post("/maintenance-requests", response_model=MaintenanceRequestOut, status_code=status.HTTP_201_CREATED)
async def report_issue(
    data: MaintenanceRequestCreate = Body(...),
    driver: Driver = Depends(get_current_driver),
    db: AsyncSession = Depends(get_db),
):
    truck = await _assigned_truck(db, driver.id)
    req = MaintenanceRequest(
        driver_id=driver.id,
        truck_id=truck.id if truck else None,
        title=data.title,
        description=data.description,
        photo_url=data.photo_url,
        status=MaintenanceRequestStatus.open,
    )
    db.add(req)
    await db.commit()
    await db.refresh(req)
    return req


# ── Push notification token registration ──────────────────────────────

@router.post("/push-token", status_code=status.HTTP_201_CREATED)
async def register_push_token(
    data: PushTokenIn = Body(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    existing = await db.execute(select(PushToken).where(PushToken.token == data.token))
    row = existing.scalar_one_or_none()
    if row:
        row.user_id = user.id
        row.platform = data.platform
    else:
        db.add(PushToken(user_id=user.id, token=data.token, platform=data.platform))
    await db.commit()
    return {"message": "registered"}


# ── CarGoRuqsat border-queue (assisted) ───────────────────────────────

def _to_status_out(record: BookingRecord | None) -> QueueStatusOut | None:
    if record is None:
        return None
    return QueueStatusOut(
        plate=record.plate,
        checkpoint=record.checkpoint,
        queue_at=record.queue_at,
        status=record.status.value,
        raw_status=record.raw_status,
    )


@router.get("/queue/status", response_model=Optional[QueueStatusOut])
async def queue_status(
    driver: Driver = Depends(get_current_driver),
    db: AsyncSession = Depends(get_db),
    client: CgrClient = Depends(get_cgr_client),
):
    """Live lookup of my assigned truck's booking in the public CarGoRuqsat registry."""
    truck = await _require_assigned_truck(db, driver.id)
    record = await client.lookup_truck(truck.plate_number)
    return _to_status_out(record)


@router.get("/queue/handoff", response_model=QueueHandoffOut)
async def queue_handoff(
    driver: Driver = Depends(get_current_driver),
    db: AsyncSession = Depends(get_db),
):
    """Deep link into the official booking flow (driver completes ЭЦП/SMS there)."""
    truck = await _assigned_truck(db, driver.id)
    watch = (
        await db.execute(select(QueueWatch).where(QueueWatch.driver_id == driver.id))
    ).scalars().first()
    return QueueHandoffOut(
        url=build_booking_handoff_url(
            checkpoint=watch.checkpoint if watch else None,
            plate=truck.plate_number if truck else None,
        )
    )


@router.get("/queue/watch", response_model=Optional[QueueWatchOut])
async def get_queue_watch(
    driver: Driver = Depends(get_current_driver),
    db: AsyncSession = Depends(get_db),
):
    res = await db.execute(
        select(QueueWatch).where(QueueWatch.driver_id == driver.id, QueueWatch.active.is_(True))
    )
    return res.scalars().first()


@router.put("/queue/watch", response_model=QueueWatchOut)
async def set_queue_watch(
    data: QueueWatchIn = Body(...),
    driver: Driver = Depends(get_current_driver),
    db: AsyncSession = Depends(get_db),
):
    """Start (or update) tracking my truck's queue at a checkpoint."""
    truck = await _require_assigned_truck(db, driver.id)
    res = await db.execute(
        select(QueueWatch).where(QueueWatch.driver_id == driver.id, QueueWatch.active.is_(True))
    )
    watch = res.scalars().first()
    if watch is None:
        watch = QueueWatch(driver_id=driver.id, plate=truck.plate_number,
                           checkpoint=data.checkpoint, country=data.country)
        db.add(watch)
    else:
        watch.plate = truck.plate_number
        watch.checkpoint = data.checkpoint
        watch.country = data.country
        watch.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(watch)
    return watch


@router.delete("/queue/watch")
async def stop_queue_watch(
    driver: Driver = Depends(get_current_driver),
    db: AsyncSession = Depends(get_db),
):
    res = await db.execute(
        select(QueueWatch).where(QueueWatch.driver_id == driver.id, QueueWatch.active.is_(True))
    )
    watch = res.scalars().first()
    if watch is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No active watch")
    watch.active = False
    watch.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return {"message": "stopped"}


@router.post("/queue/refresh", response_model=QueueRefreshOut)
async def refresh_queue_watch(
    driver: Driver = Depends(get_current_driver),
    db: AsyncSession = Depends(get_db),
    client: CgrClient = Depends(get_cgr_client),
):
    """Re-check my watch now; notify my devices if the status changed."""
    res = await db.execute(
        select(QueueWatch).where(QueueWatch.driver_id == driver.id, QueueWatch.active.is_(True))
    )
    watch = res.scalars().first()
    if watch is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No active watch")

    record, notify = await evaluate_watch(watch, client)
    if notify:
        await notify_queue_change(db, watch, record)
    await db.commit()
    return QueueRefreshOut(status=_to_status_out(record), changed=notify)


# ── Trips (driver-scoped) ─────────────────────────────────────────────

_DRIVER_START_STATUSES = {TripStatus.en_route, TripStatus.loading}


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
    res = await db.execute(select(Trip).where(Trip.id == trip_id))
    trip = res.scalar_one_or_none()
    if trip is None or trip.driver_id != driver.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trip not found")

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


async def _own_trip_or_404(db: AsyncSession, trip_id: uuid.UUID, driver: Driver) -> Trip:
    """Fetch a trip and assert it is assigned to the signed-in driver."""
    res = await db.execute(select(Trip).where(Trip.id == trip_id))
    trip = res.scalar_one_or_none()
    if trip is None or trip.driver_id != driver.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trip not found")
    return trip


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

    trip = await _own_trip_or_404(db, trip_id, driver)

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
    await _own_trip_or_404(db, trip_id, driver)
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
    await _own_trip_or_404(db, trip_id, driver)
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
    trip = await _own_trip_or_404(db, trip_id, driver)
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
    await _own_trip_or_404(db, trip_id, driver)
    report = await get_report(db, trip_id)
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not started")
    report.status = TripReportStatus.submitted
    report.submitted_at = datetime.now(timezone.utc)
    await db.commit()
    return build_report_out(report)
