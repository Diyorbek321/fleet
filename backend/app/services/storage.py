"""Local-disk storage adapter for driver-uploaded trip documents.

Files are written under ``settings.upload_dir`` (a persistent Docker volume on
the server) and served back through the API via short-lived, HMAC-signed URLs —
so the bytes never need a public bucket and an ``<img src>`` works without an
auth header. The signature is keyed by ``JWT_SECRET_KEY``.

The public surface (``put_object`` / ``presigned_get_url`` / ``delete_object`` /
``is_configured``) is intentionally S3-shaped so callers stay storage-agnostic;
swapping to S3/Spaces later is a drop-in replacement of this module.
"""
from __future__ import annotations

import hashlib
import hmac
import time
from pathlib import Path
from urllib.parse import quote

from app.core.config import settings

# Files are served from this API path; the router in app/routers/files.py reads it.
_FILES_PATH = "/api/files"


def is_configured() -> bool:
    """Local disk is always available once an upload dir is set (it always is)."""
    return bool(settings.upload_dir)


def _root() -> Path:
    root = Path(settings.upload_dir)
    root.mkdir(parents=True, exist_ok=True)
    return root


def _resolve(key: str) -> Path:
    """Resolve a storage key to an absolute path, guarding against traversal."""
    root = _root().resolve()
    path = (root / key).resolve()
    if not str(path).startswith(str(root)):
        raise ValueError("Invalid storage key")
    return path


def put_object(key: str, data: bytes, content_type: str) -> None:
    """Store an object under ``key`` (content_type kept by the file extension)."""
    path = _resolve(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def delete_object(key: str) -> None:
    """Delete the object at ``key`` (safe if already gone)."""
    path = _resolve(key)
    if path.exists():
        path.unlink()


def read_object(key: str) -> bytes:
    return _resolve(key).read_bytes()


def object_exists(key: str) -> bool:
    return _resolve(key).exists()


def _sign(key: str, expires_at: int) -> str:
    msg = f"{key}:{expires_at}".encode()
    secret = settings.jwt_secret_key.encode()
    return hmac.new(secret, msg, hashlib.sha256).hexdigest()


def verify_signature(key: str, expires_at: int, signature: str) -> bool:
    """True when ``signature`` is valid for ``key`` and not yet expired."""
    if expires_at < int(time.time()):
        return False
    return hmac.compare_digest(signature, _sign(key, expires_at))


def presigned_get_url(key: str, expires: int = 3600) -> str:
    """An absolute, time-limited URL to read the object at ``key``.

    Absolute (using ``API_PUBLIC_URL``) so the manager panel — served from a
    different origin than the API — can load it directly in an ``<img>``.
    """
    expires_at = int(time.time()) + expires
    sig = _sign(key, expires_at)
    base = (settings.api_public_url or "").rstrip("/")
    return f"{base}{_FILES_PATH}/{quote(key)}?exp={expires_at}&sig={sig}"
