"""Self-scoped endpoints for the driver mobile app (``/api/me``).

Every endpoint in this package is strictly scoped to the authenticated driver
via ``get_current_driver`` — a driver can only ever read or write their own
data, their assigned truck, and their own shifts/requests/trips.

Split by what the driver is doing, because as one module this was 750 lines and
the shared ownership helpers were buried in the middle of it:

* ``profile``     — who I am, what I drive, shifts, location pings, push tokens
* ``spending``    — fuel logs and daily cash expenses
* ``maintenance`` — service history I can read, issues I can report
* ``queue``       — CarGoRuqsat border-queue watch and handoff
* ``trips``       — my trips, their documents, and the expense report

The sub-routers all carry the same prefix and tag (see ``_common``), so the
mounted paths and the generated OpenAPI document are identical to before — this
is a file layout change, not an API change.
"""
from __future__ import annotations

from fastapi import APIRouter

from app.routers.me import maintenance, profile, queue, spending, trips

router = APIRouter()

for _sub in (profile, spending, maintenance, queue, trips):
    router.include_router(_sub.router)

__all__ = ["router"]
