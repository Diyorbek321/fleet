"""Owner alerts, recorded for the panel's bell and pushed to open panels.

Called from ``bus.notify_owner`` for every alert, before any Telegram gating:
the panel has no quiet hours, no mute list and no linked-chat requirement. A
dispatcher looking at the screen at 03:00 should see what happened at 03:00.

Deduped on the alert's own ``dedupe_key``, so a watcher restating a fact on
every tick — or the bus retrying one deferred by quiet hours — still leaves a
single row. Never raises, like the bus itself.
"""
from __future__ import annotations

import html
import re
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger
from app.core.ws import ws_manager
from app.models.panel_notifications import PanelNotification

__all__ = ["record_panel_notification", "prune_panel_notifications", "plain_text"]

_TAG = re.compile(r"<[^>]+>")

# The "and N more" line exists because a Telegram chat must not get twenty
# pings at once. The panel lists all twenty anyway, so the summary is noise.
_OVERFLOW_MARKER = ":overflow:"


def plain_text(body_html: str) -> str:
    """The Telegram body without its markup. The panel renders text only."""
    return html.unescape(_TAG.sub("", body_html)).strip()


async def record_panel_notification(db: AsyncSession, org_id: uuid.UUID, alert) -> bool:
    """Store ``alert`` for the org's panel, once. Returns whether it was new."""
    if _OVERFLOW_MARKER in alert.dedupe_key:
        return False
    try:
        now = datetime.now(timezone.utc)
        stmt = (
            pg_insert(PanelNotification)
            .values(
                id=uuid.uuid4(),
                org_id=org_id,
                kind=alert.kind.value,
                severity=alert.severity.value,
                title=alert.title[:300],
                body=plain_text(alert.body or ""),
                path=(alert.path or None) and alert.path[:300],
                dedupe_key=alert.dedupe_key[:200],
                created_at=now,
            )
            .on_conflict_do_nothing(constraint="uq_panel_notifications_org_key")
            .returning(PanelNotification.id)
        )
        new_id = (await db.execute(stmt)).scalar_one_or_none()
        await db.commit()
    except Exception:  # noqa: BLE001 — the Telegram half must still go out.
        logger.exception("panel_notification_record_failed", org_id=str(org_id))
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            logger.exception("panel_notification_rollback_failed")
        return False

    if new_id is None:
        return False

    # Only a hint that the bell changed; the panel refetches the list itself,
    # so what it shows always comes through the org-scoped, role-checked API.
    try:
        await ws_manager.broadcast_to_org(
            str(org_id),
            {"type": "notification", "id": str(new_id), "severity": alert.severity.value},
        )
    except Exception:  # noqa: BLE001
        logger.exception("panel_notification_broadcast_failed", org_id=str(org_id))
    return True


async def prune_panel_notifications(db: AsyncSession, older_than_days: int = 30) -> int:
    """Drop bell entries nobody will scroll back to."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, older_than_days))
    result = await db.execute(delete(PanelNotification).where(PanelNotification.created_at < cutoff))
    await db.commit()
    return int(result.rowcount or 0)
