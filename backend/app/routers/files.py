"""Serve driver-uploaded files via short-lived, HMAC-signed URLs.

No session auth: the signature (minted by ``storage.presigned_get_url``) IS the
authorization, so an ``<img src>`` in the manager panel loads the image directly.
Signatures are keyed by ``JWT_SECRET_KEY`` and expire, so links can't be guessed
or reused indefinitely.
"""
from __future__ import annotations

import mimetypes

from fastapi import APIRouter, HTTPException, Query, Response, status

from app.services import storage

router = APIRouter(prefix="/api/files", tags=["Files"])


@router.get("/{key:path}")
async def get_file(
    key: str,
    exp: int = Query(...),
    sig: str = Query(...),
) -> Response:
    if not storage.verify_signature(key, exp, sig):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or expired link",
        )
    if not storage.object_exists(key):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    data = storage.read_object(key)
    media_type = mimetypes.guess_type(key)[0] or "application/octet-stream"
    return Response(
        content=data,
        media_type=media_type,
        headers={"Cache-Control": "private, max-age=3600"},
    )
