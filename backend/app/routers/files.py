"""Serve driver-uploaded files via short-lived, HMAC-signed URLs.

No session auth: the signature (minted by ``storage.presigned_get_url``) IS the
authorization, so an ``<img src>`` in the manager panel loads the image directly.
Signatures are keyed by ``JWT_SECRET_KEY`` and expire, so links can't be guessed
or reused indefinitely.

Two properties this endpoint has to hold that are easy to lose:

* **It streams.** These are phone photos of freight paperwork — up to 10 MB
  each, a dozen on one trip page. Reading each into memory before responding
  makes a handful of viewers a memory problem on a small droplet.
* **It never lets a browser reinterpret a file.** The Content-Type is derived
  from the stored extension, which the upload allowlist controls, and
  ``nosniff`` stops the browser from guessing something more dangerous.
"""
from __future__ import annotations

import mimetypes
from pathlib import PurePosixPath

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import FileResponse

from app.core.rate_limit import limiter
from app.services import storage

router = APIRouter(prefix="/api/files", tags=["Files"])


# ``response_model=None`` is load-bearing. This module has
# ``from __future__ import annotations``, so the ``-> FileResponse`` return
# annotation reaches FastAPI as the *string* "FileResponse"; it cannot see that
# this is a Starlette response class rather than a schema, tries to build a
# pydantic TypeAdapter from an unresolved ForwardRef, and every request for
# /openapi.json then dies with PydanticUserError. The endpoint itself keeps
# working, which is what made this easy to ship unnoticed.
@router.get("/{key:path}", response_model=None)
# Generous: one trip page pulls every document on it at once, and a signature
# is required regardless. The cap is here so a leaked link cannot be used to
# pull the same file in a loop as a cheap way to saturate the box.
@limiter.limit("300/minute")
async def get_file(
    request: Request,
    key: str,
    exp: int = Query(...),
    sig: str = Query(...),
) -> FileResponse:
    if not storage.verify_signature(key, exp, sig):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Ссылка неверна или устарела",
        )
    if not storage.object_exists(key):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Не найдено")

    media_type = mimetypes.guess_type(key)[0] or "application/octet-stream"
    return FileResponse(
        storage.object_path(key),
        media_type=media_type,
        headers={
            "Cache-Control": "private, max-age=3600",
            # The stored extension decides the type; the browser does not get
            # to overrule it by sniffing the bytes.
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": f'inline; filename="{PurePosixPath(key).name}"',
        },
    )
