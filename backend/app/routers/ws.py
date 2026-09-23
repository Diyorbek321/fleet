from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import decode_token
from app.core.ws import ws_manager
from app.models.enums import UserRole
from app.models.organizations import Organization
from app.models.users import User

router = APIRouter(tags=["WebSocket"])


async def _authorized_org_id(db: AsyncSession, token: str) -> uuid.UUID | None:
    """Org this token may subscribe to, or None if it may not subscribe at all.

    The org is taken from the *database* record of the user, not from the token's
    ``orgId`` claim, and the tenant's ``is_active`` is re-read here. Without this
    a suspended customer keeps their socket — every REST call 403s, but the live
    truck feed (the thing they are actually paying for) keeps streaming. One
    round-trip per connection, not per message, so the cost is negligible.
    """
    try:
        payload = decode_token(token)
    except Exception:
        return None

    try:
        user_id = uuid.UUID(payload.get("userId", ""))
    except (ValueError, TypeError):
        return None

    row = (
        await db.execute(
            select(User, Organization.is_active)
            .join(Organization, Organization.id == User.org_id)
            .where(User.id == user_id)
        )
    ).first()
    if row is None:
        return None

    user, org_is_active = row
    if not org_is_active and user.role is not UserRole.superadmin:
        return None
    return user.org_id


# The subprotocol a client offers alongside its credential, and the one we
# select in reply. Selecting the plain name — never the credential-bearing one —
# keeps the token out of the handshake *response* as well as the request line.
WS_SUBPROTOCOL = "fleetwatch.v1"
_AUTH_SUBPROTOCOL_PREFIX = "fleetwatch.auth."


def _token_from_subprotocol(websocket: WebSocket) -> str | None:
    """Pull the access token out of ``Sec-WebSocket-Protocol``, if it is there.

    A browser cannot set an ``Authorization`` header on ``new WebSocket()``, so
    the token used to ride in the query string — where Caddy's access log, and
    every proxy in front of it, wrote it to disk in cleartext alongside the
    request line. The subprotocol header carries it instead: same handshake,
    same origin checks, but nothing logs a string that grants access to a
    fleet for the next thirty minutes.
    """
    offered = websocket.headers.get("sec-websocket-protocol")
    if not offered:
        return None
    for entry in offered.split(","):
        entry = entry.strip()
        if entry.startswith(_AUTH_SUBPROTOCOL_PREFIX):
            return entry[len(_AUTH_SUBPROTOCOL_PREFIX):] or None
    return None


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    token: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    # Preferred: Sec-WebSocket-Protocol. The ?token= query parameter is still
    # accepted for clients that predate this — the mobile app opens no socket,
    # but a shipped web bundle lives in browser caches for as long as it lives.
    subprotocol_token = _token_from_subprotocol(websocket)
    token = subprotocol_token or token
    if not token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Missing token")
        return

    authorized = await _authorized_org_id(db, token)
    if authorized is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid token")
        return

    # str() because that is the bucket key every broadcaster uses (gps.py, me.py).
    org_id = str(authorized)
    await ws_manager.connect(
        websocket,
        org_id,
        subprotocol=WS_SUBPROTOCOL if subprotocol_token else None,
    )
    try:
        while True:
            # Ignore inbound text (clients may send "ping" keep-alives).
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket, org_id)
    except Exception:
        ws_manager.disconnect(websocket, org_id)
