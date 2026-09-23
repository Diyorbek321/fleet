"""How the live-map socket is authenticated, and where the credential travels.

A browser cannot put an ``Authorization`` header on ``new WebSocket()``. The
token therefore used to ride in the query string, where Caddy — and any proxy in
front of it — wrote it into an access log in cleartext. It now rides in
``Sec-WebSocket-Protocol`` instead, which no proxy logs by default.

The handshake detail matters more than it looks: a browser that offered
subprotocols *fails the connection* unless the server echoes exactly one back.
Get that wrong and the live map goes dark for every dispatcher at once, with a
green backend and nothing in the logs.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pytest
from fastapi import WebSocketDisconnect
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.routers.ws import (
    WS_SUBPROTOCOL,
    _token_from_subprotocol,
    websocket_endpoint,
)


# eq=False keeps identity hashing: the connection manager stores sockets in a
# set, and a dataclass with a generated __eq__ is unhashable.
@dataclass(eq=False)
class FakeWebSocket:
    """Just enough WebSocket to drive the endpoint without a real handshake."""

    headers: dict[str, str] = field(default_factory=dict)
    accepted_with: object = "<not accepted>"
    closed: tuple[int, str] | None = None

    async def accept(self, subprotocol=None):
        self.accepted_with = subprotocol

    async def close(self, code: int = 1000, reason: str = ""):
        self.closed = (code, reason)

    async def receive_text(self) -> str:
        raise WebSocketDisconnect(code=1000)


@pytest.mark.parametrize(
    "offered, expected",
    [
        ("fleetwatch.v1, fleetwatch.auth.TOKEN123", "TOKEN123"),
        ("fleetwatch.auth.TOKEN123", "TOKEN123"),
        ("fleetwatch.v1", None),
        ("", None),
        ("fleetwatch.auth.", None),  # prefix with nothing behind it is not a token
        ("something.else, fleetwatch.auth.abc.def-ghi_jkl", "abc.def-ghi_jkl"),
    ],
)
def test_token_is_read_out_of_the_offered_subprotocols(offered, expected):
    ws = FakeWebSocket(headers={"sec-websocket-protocol": offered} if offered else {})
    assert _token_from_subprotocol(ws) == expected


async def test_subprotocol_token_connects_and_echoes_the_plain_name(
    db: AsyncSession, admin_token: str
):
    """The server must select a subprotocol, and never the one holding the key."""
    ws = FakeWebSocket(
        headers={"sec-websocket-protocol": f"{WS_SUBPROTOCOL}, fleetwatch.auth.{admin_token}"}
    )

    await websocket_endpoint(ws, token=None, db=db)

    assert ws.closed is None, f"connection refused: {ws.closed}"
    assert ws.accepted_with == WS_SUBPROTOCOL
    assert admin_token not in str(ws.accepted_with)


async def test_query_token_still_works_for_a_cached_bundle(
    db: AsyncSession, admin_token: str
):
    """Browsers hold a shipped bundle for a long time; don't cut them off."""
    ws = FakeWebSocket()

    await websocket_endpoint(ws, token=admin_token, db=db)

    assert ws.closed is None
    # Nothing was offered, so nothing may be echoed — replying with a
    # subprotocol the client never offered fails the handshake too.
    assert ws.accepted_with is None


async def test_a_bad_subprotocol_token_is_refused(db: AsyncSession):
    ws = FakeWebSocket(headers={"sec-websocket-protocol": "fleetwatch.auth.not-a-jwt"})

    await websocket_endpoint(ws, token=None, db=db)

    assert ws.closed is not None
    assert ws.closed[1] == "Invalid token"


async def test_a_suspended_org_cannot_open_a_socket(
    client: AsyncClient, db: AsyncSession, admin_token: str
):
    """Every REST call 403s when a customer is switched off.

    The live truck feed is the thing they are actually paying for, so it has to
    stop at the same moment — not whenever the socket happens to drop.
    """
    from sqlalchemy import select

    from app.models.organizations import Organization

    org = (await db.execute(select(Organization).where(Organization.name == "Test Org"))).scalar_one()
    org.is_active = False
    await db.commit()

    ws = FakeWebSocket(headers={"sec-websocket-protocol": f"fleetwatch.auth.{admin_token}"})
    await websocket_endpoint(ws, token=None, db=db)

    assert ws.closed is not None, "a suspended customer kept their live feed"
