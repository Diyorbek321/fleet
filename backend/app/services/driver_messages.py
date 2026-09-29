"""Put a message in a driver's inbox and on their phone.

The row is written and committed before the push goes out. That ordering is
the same trade as the border-queue notifier makes: a push that fails still
leaves the message in the app's inbox, and a retry can never produce a second
copy of an automatic warning, because the ``dedupe_key`` row already exists.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger
from app.models.driver_app import PushToken
from app.models.driver_messages import DriverMessage, DriverMessageKind
from app.models.users import User
from app.services import push

__all__ = ["send_driver_message"]


async def _driver_tokens(db: AsyncSession, driver_id: uuid.UUID) -> list[PushToken]:
    rows = await db.execute(
        select(PushToken).join(User, User.id == PushToken.user_id).where(User.driver_id == driver_id)
    )
    return list(rows.scalars().all())


async def send_driver_message(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    driver_id: uuid.UUID,
    kind: DriverMessageKind,
    title: str,
    body: str,
    truck_id: uuid.UUID | None = None,
    sent_by_user_id: uuid.UUID | None = None,
    dedupe_key: str | None = None,
) -> DriverMessage | None:
    """Store the message, then push it to every device the driver is signed in on.

    Returns the stored message, or None when ``dedupe_key`` was already used in
    this organization — the driver has been told this already.
    """
    now = datetime.now(timezone.utc)
    stmt = (
        pg_insert(DriverMessage)
        .values(
            id=uuid.uuid4(),
            org_id=org_id,
            driver_id=driver_id,
            truck_id=truck_id,
            sent_by_user_id=sent_by_user_id,
            kind=kind.value,
            title=title,
            body=body,
            dedupe_key=dedupe_key,
            devices_delivered=0,
            created_at=now,
        )
        .on_conflict_do_nothing(constraint="uq_driver_messages_org_key")
        .returning(DriverMessage.id)
    )
    message_id = (await db.execute(stmt)).scalar_one_or_none()
    if message_id is None:
        return None
    await db.commit()

    data: dict[str, Any] = {"kind": "message", "message_id": str(message_id)}
    outcome = await push.send_to_tokens(
        db, await _driver_tokens(db, driver_id), title=title, body=body, data=data
    )

    message = await db.get(DriverMessage, message_id)
    if message is not None:
        message.devices_delivered = outcome.accepted
    await db.commit()

    logger.info(
        "driver_message_sent",
        driver_id=str(driver_id),
        kind=kind.value,
        delivered=outcome.accepted,
    )
    return message
