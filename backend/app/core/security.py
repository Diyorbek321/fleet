from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Dict
from jose import jwt
from passlib.context import CryptContext
from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)

def create_access_token(subject: Dict[str, Any]) -> str:
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {
        **subject,
        "iat": now,
        "exp": expire,
        "jti": secrets.token_urlsafe(16),  # unique per token to prevent collisions within same second
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)

def create_refresh_token(subject: Dict[str, Any]) -> str:
    now = datetime.now(timezone.utc)
    expire = now + timedelta(days=settings.refresh_token_expire_days)
    payload = {
        **subject,
        "iat": now,
        "exp": expire,
        "type": "refresh",
        "jti": secrets.token_urlsafe(16),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)

def decode_token(token: str) -> Dict[str, Any]:
    return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])


def password_stamp(changed_at: datetime) -> int:
    """The value carried in a token's ``pwdAt`` claim.

    Whole microseconds, not seconds: at second granularity a reset performed in
    the same second a token was minted would compare equal, and the token that
    the reset was meant to kill would survive. Not a float either — the claim
    round-trips through JSON, and 1.7e9 seconds with microseconds is at the edge
    of what a double represents exactly.
    """
    return int(changed_at.timestamp() * 1_000_000)


def token_predates_password_change(payload: Dict[str, Any], changed_at: datetime) -> bool:
    """Whether this token was issued before the account's current password.

    A token with no ``pwdAt`` at all was minted before this mechanism existed
    and is treated as stale, so the guarantee holds from the deploy onward
    rather than from each user's next sign-in.
    """
    stamped = payload.get("pwdAt")
    if not isinstance(stamped, int):
        return True
    return stamped < password_stamp(changed_at)
