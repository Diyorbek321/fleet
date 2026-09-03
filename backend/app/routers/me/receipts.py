"""Read a photographed receipt into a suggested expense line — no writes.

The endpoint is deliberately the odd one out in this package: it takes a driver's
photo, returns a reading, and touches no table. What the driver confirms is saved
by ``PUT /api/me/trips/{trip_id}/report`` like every hand-typed line before it,
so a misread total is a suggestion the driver overwrites rather than a row
somebody has to find later. See :mod:`app.services.receipts` for why that split
is the whole feature.

Because nothing is stored, there is no trip in the path and no ownership check
beyond authentication: the scan reads bytes the driver just supplied and hands
them straight back.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel

from app.deps.auth import get_current_driver
from app.models.drivers import Driver
from app.models.enums import TripReportCountry, TripReportExpenseCategory
from app.routers.me._common import PREFIX, TAGS
from app.services.receipts import (
    ALLOWED_CONTENT_TYPES,
    MAX_IMAGE_BYTES,
    ReceiptScanNotConfigured,
    ReceiptScanUnavailable,
    ReceiptUnreadable,
    scan_receipt,
)

router = APIRouter(prefix=PREFIX, tags=TAGS)


class ReceiptScanOut(BaseModel):
    """A suggestion, not a saved row — the client must have the driver confirm it.

    ``confidence`` is 0..1 for the reading as a whole so the app can present a
    shaky total differently from a crisp one instead of showing every reading
    with the same authority.
    """

    country: TripReportCountry
    category: TripReportExpenseCategory
    amount: float
    currency: str
    vendor: Optional[str] = None
    confidence: float


@router.post("/receipts/scan", response_model=ReceiptScanOut)
async def scan_receipt_photo(
    file: UploadFile = File(...),
    driver: Driver = Depends(get_current_driver),
):
    """Read one receipt photo into a suggested country/category/amount.

    Stores nothing, neither the image nor the reading.
    """
    content_type = (file.content_type or "").split(";")[0].strip().lower()
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Upload a JPEG, PNG or WebP photo",
        )

    # Starlette knows the size before the body is buffered for a spooled upload,
    # so an oversized file is refused without reading it.
    declared = getattr(file, "size", None)
    if isinstance(declared, int) and declared > MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Photo too large (max 8MB)",
        )

    image = await file.read()
    if len(image) > MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Photo too large (max 8MB)",
        )
    if not image:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The uploaded photo is empty",
        )

    try:
        reading = await scan_receipt(image, content_type)
    except ReceiptScanNotConfigured as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    except ReceiptUnreadable as exc:
        # 422, not 500: a model answering with a category that does not exist is
        # an expected outcome of asking a model, and the driver's next step —
        # type the line by hand — is what they do today anyway.
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    except ReceiptScanUnavailable as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))

    return ReceiptScanOut(
        country=reading.country,
        category=reading.category,
        amount=float(reading.amount),
        currency=reading.currency,
        vendor=reading.vendor,
        confidence=reading.confidence,
    )
