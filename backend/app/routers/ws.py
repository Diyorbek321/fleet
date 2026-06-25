from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from app.core.security import decode_token
from app.core.ws import ws_manager

router = APIRouter(tags=["WebSocket"])


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str | None = None):
    # Token is passed as ?token=... — browsers can't set headers on WebSocket().
    if not token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Missing token")
        return

    try:
        payload = decode_token(token)
    except Exception:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid token")
        return

    org_id = payload.get("orgId")
    if not org_id:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Missing org claim")
        return

    await ws_manager.connect(websocket, org_id)
    try:
        while True:
            # Ignore inbound text (clients may send "ping" keep-alives).
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket, org_id)
    except Exception:
        ws_manager.disconnect(websocket, org_id)
