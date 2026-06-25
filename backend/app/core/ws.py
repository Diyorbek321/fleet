from __future__ import annotations

from typing import Any, Dict, Set

from fastapi import WebSocket


class ConnectionManager:
    """Tenant-scoped WebSocket fan-out.

    Connections are bucketed by ``org_id`` so a live-map broadcast (truck
    location, geofence event) only ever reaches sockets belonging to the same
    organization. Without this every customer's dashboard would receive every
    other customer's real-time GPS.

    Note: this is in-process. With multiple app replicas a GPS point ingested on
    replica A is only pushed to sockets on replica A. For true horizontal scale
    of the live map, back this with Redis pub/sub (each replica subscribes and
    re-broadcasts to its local org sockets). Tracked as a follow-up; the org
    scoping here is the correctness/security fix.
    """

    def __init__(self) -> None:
        self._by_org: Dict[str, Set[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, org_id: str) -> None:
        await websocket.accept()
        self._by_org.setdefault(org_id, set()).add(websocket)

    def disconnect(self, websocket: WebSocket, org_id: str) -> None:
        conns = self._by_org.get(org_id)
        if conns is not None:
            conns.discard(websocket)
            if not conns:
                self._by_org.pop(org_id, None)

    async def broadcast_to_org(self, org_id: str, message: Any) -> None:
        conns = self._by_org.get(org_id)
        if not conns:
            return
        dead = []
        for ws in list(conns):
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws, org_id)


ws_manager = ConnectionManager()
