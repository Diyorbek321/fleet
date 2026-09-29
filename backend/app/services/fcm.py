"""Push to Android phones straight through Firebase Cloud Messaging (HTTP v1).

The app used to register Expo push tokens, which route every message through
Expo's servers and need an Expo account on top of Firebase. It now registers
the phone's own FCM token, and the server sends to Firebase itself: one
credential (a Firebase service-account key), one hop.

Authentication is the service-account OAuth flow done by hand — a JWT signed
with the key's RSA private key, exchanged for a one-hour access token — using
python-jose, which the backend already carries for its own JWTs, rather than
pulling in google-auth for one call.

Never raises. Every caller is a background sweep or a request that has already
done its real work; a push that cannot go out must not undo either.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from jose import jwt

from app.core.config import settings
from app.core.logging import logger

_TOKEN_URL = "https://oauth2.googleapis.com/token"
_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
_SEND_URL = "https://fcm.googleapis.com/v1/projects/{project}/messages:send"
_TIMEOUT = 15.0

# The Android channel the app creates (mobile/src/lib/push.ts) and the small
# icon it ships (res/drawable-*/notification_icon.png). Named here so a
# message that arrives while the app is closed — displayed by Android itself,
# not by the app — still uses them.
ANDROID_CHANNEL_ID = "default"
ANDROID_ICON = "notification_icon"
ANDROID_COLOR = "#14b8a6"


@dataclass(frozen=True)
class _Credentials:
    project_id: str
    client_email: str
    private_key: str


@dataclass(frozen=True)
class FcmResult:
    ok: bool
    # Firebase says this token will never work again: uninstalled, or reissued.
    dead: bool = False


_credentials_cache: _Credentials | None = None
_access_token: tuple[str, float] | None = None  # (token, expires at, epoch s)


def _load_credentials() -> _Credentials | None:
    global _credentials_cache
    if _credentials_cache is not None:
        return _credentials_cache
    path = settings.fcm_credentials_file.strip()
    if not path or not Path(path).is_file():
        return None
    try:
        raw = json.loads(Path(path).read_text())
        _credentials_cache = _Credentials(
            project_id=raw["project_id"],
            client_email=raw["client_email"],
            private_key=raw["private_key"],
        )
    except (OSError, ValueError, KeyError):
        logger.exception("fcm_credentials_unreadable", path=path)
        return None
    return _credentials_cache


def is_configured() -> bool:
    return _load_credentials() is not None


async def _get_access_token(client: httpx.AsyncClient, creds: _Credentials) -> str | None:
    global _access_token
    now = time.time()
    if _access_token and _access_token[1] - 60 > now:
        return _access_token[0]

    assertion = jwt.encode(
        {
            "iss": creds.client_email,
            "scope": _SCOPE,
            "aud": _TOKEN_URL,
            "iat": int(now),
            "exp": int(now) + 3600,
        },
        creds.private_key,
        algorithm="RS256",
    )
    try:
        resp = await client.post(
            _TOKEN_URL,
            data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion},
        )
        resp.raise_for_status()
        body = resp.json()
    except Exception:  # noqa: BLE001
        logger.exception("fcm_access_token_failed")
        return None
    _access_token = (body["access_token"], now + float(body.get("expires_in", 3600)))
    return _access_token[0]


def _message(token: str, title: str, body: str, data: dict[str, Any] | None) -> dict:
    return {
        "message": {
            "token": token,
            "notification": {"title": title, "body": body},
            # FCM data values must be strings.
            **({"data": {k: str(v) for k, v in data.items()}} if data else {}),
            "android": {
                "priority": "HIGH",
                "notification": {
                    "channel_id": ANDROID_CHANNEL_ID,
                    "icon": ANDROID_ICON,
                    "color": ANDROID_COLOR,
                    "sound": "default",
                },
            },
        }
    }


def _is_dead(resp: httpx.Response) -> bool:
    """UNREGISTERED is the one answer that means "delete this token".

    A 400 is deliberately not treated as dead: it is just as often our own
    payload being wrong, and reading it as "bad token" would wipe every driver's
    registration on the first malformed message.
    """
    if resp.status_code == 404:
        return True
    try:
        details = resp.json().get("error", {}).get("details", [])
    except ValueError:
        return False
    return any(d.get("errorCode") == "UNREGISTERED" for d in details if isinstance(d, dict))


async def send(
    tokens: list[str],
    *,
    title: str,
    body: str,
    data: dict[str, Any] | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> list[FcmResult]:
    """One result per token, in order. All failures when FCM is not configured."""
    creds = _load_credentials()
    if creds is None:
        if tokens:
            logger.warning("fcm_not_configured", devices=len(tokens))
        return [FcmResult(ok=False) for _ in tokens]

    results: list[FcmResult] = []
    async with httpx.AsyncClient(timeout=_TIMEOUT, transport=transport) as client:
        access = await _get_access_token(client, creds)
        if access is None:
            return [FcmResult(ok=False) for _ in tokens]
        url = _SEND_URL.format(project=creds.project_id)
        headers = {"Authorization": f"Bearer {access}"}
        for token in tokens:
            try:
                resp = await client.post(url, json=_message(token, title, body, data), headers=headers)
            except httpx.HTTPError as exc:
                logger.warning("fcm_send_transport_error", error=str(exc))
                results.append(FcmResult(ok=False))
                continue
            if resp.status_code == 200:
                results.append(FcmResult(ok=True))
                continue
            dead = _is_dead(resp)
            if not dead:
                logger.warning("fcm_send_failed", status=resp.status_code, body=resp.text[:300])
            results.append(FcmResult(ok=False, dead=dead))
    return results


def reset_cache() -> None:
    """Forget loaded credentials and the access token. Tests, and key rotation."""
    global _credentials_cache, _access_token
    _credentials_cache = None
    _access_token = None
