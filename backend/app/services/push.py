"""Push delivery to drivers' phones.

Two kinds of token reach ``push_tokens``. Current app builds register the
phone's own Firebase (FCM) token and are sent to through Firebase directly
(``app.services.fcm``). Expo push tokens are still honoured and routed through
Expo, so any build registering them keeps working; the two are told apart by
format, since an Expo token always looks like ``ExponentPushToken[...]``.

Delivery is best-effort by design. Every caller is either a background sweep or
a request that has already done the useful work; a notification that cannot be
sent must never roll back the state change that prompted it.

Token rows are deleted from the passed session but not committed — the callers
(`poll_active_watches`, the `/api/me/queue/refresh` handler) commit once at the
end of their own unit of work.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

import httpx

from app.core.config import settings
from app.core.logging import logger
from app.models.driver_app import PushToken
from app.services import fcm

EXPO_PUSH_ENDPOINT = "https://exp.host/--/api/v2/push/send"

# Expo rejects a request carrying more than 100 messages.
BATCH_SIZE = 100

# Expo signals a token that can never be delivered to again — the app was
# uninstalled, or the token was reissued. Anything else is transient.
_DEAD_TOKEN_ERROR = "DeviceNotRegistered"

_TIMEOUT = 15.0


@dataclass(frozen=True)
class PushOutcome:
    """What one call achieved. Counts are per device, not per driver."""

    accepted: int = 0
    failed: int = 0
    skipped: int = 0
    removed: list[str] = field(default_factory=list)


def is_expo_token(token: str) -> bool:
    """Whether Expo's endpoint will accept this token.

    Worth checking before sending: Expo rejects a whole request when any token
    in it is malformed, so one stale row of another format would silently cost
    every other device in the same batch.
    """
    return token.startswith(("ExponentPushToken[", "ExpoPushToken["))


async def send_to_tokens(
    db,
    tokens: Sequence[PushToken],
    *,
    title: str,
    body: str,
    data: dict[str, Any] | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> PushOutcome:
    """Deliver one notification to every given device.

    ``transport`` exists so tests can assert on the outgoing request without
    reaching the network; production never passes it.
    """
    deliverable = [t for t in tokens if is_expo_token(t.token)]
    native = [t for t in tokens if not is_expo_token(t.token)]
    skipped = 0

    accepted = 0
    failed = 0
    removed: list[str] = []

    if native:
        results = await fcm.send(
            [t.token for t in native], title=title, body=body, data=data, transport=transport
        )
        for row, result in zip(native, results):
            if result.ok:
                accepted += 1
                continue
            failed += 1
            if result.dead:
                removed.append(row.token)
                await db.delete(row)

    if not deliverable:
        if removed:
            logger.info("push_tokens_removed", count=len(removed), reason="UNREGISTERED")
        logger.info("push_sent", accepted=accepted, failed=failed, skipped=skipped)
        return PushOutcome(accepted=accepted, failed=failed, skipped=skipped, removed=removed)

    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    # Optional: an access token makes the send authenticated, which Expo
    # requires once "enhanced security" is switched on for a project.
    if settings.expo_access_token:
        headers["Authorization"] = f"Bearer {settings.expo_access_token}"

    async with httpx.AsyncClient(timeout=_TIMEOUT, transport=transport) as client:
        for batch in _batched(deliverable, BATCH_SIZE):
            messages = [
                {
                    "to": row.token,
                    "title": title,
                    "body": body,
                    "sound": "default",
                    "priority": "high",
                    **({"data": data} if data else {}),
                }
                for row in batch
            ]
            try:
                resp = await client.post(EXPO_PUSH_ENDPOINT, json=messages, headers=headers)
                resp.raise_for_status()
                tickets = resp.json().get("data") or []
            except Exception:  # noqa: BLE001 — never let delivery break the caller
                logger.exception("push_send_failed", devices=len(batch))
                failed += len(batch)
                continue

            for row, ticket in zip(batch, tickets):
                if ticket.get("status") == "ok":
                    accepted += 1
                    continue

                failed += 1
                error = (ticket.get("details") or {}).get("error")
                if error == _DEAD_TOKEN_ERROR:
                    removed.append(row.token)
                    await db.delete(row)
                else:
                    logger.warning(
                        "push_ticket_error",
                        error=error,
                        message=ticket.get("message"),
                    )

            # More tickets than messages should be impossible; fewer means Expo
            # answered partially, and those devices simply were not delivered to.
            if len(tickets) < len(batch):
                failed += len(batch) - len(tickets)

    if removed:
        logger.info("push_tokens_removed", count=len(removed), reason=_DEAD_TOKEN_ERROR)

    logger.info("push_sent", accepted=accepted, failed=failed, skipped=skipped)
    return PushOutcome(accepted=accepted, failed=failed, skipped=skipped, removed=removed)


def _batched(items: Sequence[PushToken], size: int) -> Iterable[Sequence[PushToken]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


# ── Message text ─────────────────────────────────────────────────────────────
#
# Russian, matching the customer-facing Telegram messages in
# ``app/services/telegram.py``. The driver app is translated, but a push
# notification is rendered by the OS from what the server sends, and the server
# has no record of which language a driver picked — so this follows the same
# choice the rest of the platform's outbound text already makes.

_QUEUE_TITLES = {
    "late": "⏰ Вы опаздываете в очередь",
    "revoked": "❌ Пропуск отозван",
    "crossed": "✅ Вы прошли границу",
    "in_queue": "🕓 Вы в очереди",
    "check_failed": "⚠️ Проверка не пройдена",
    "none": "ℹ️ Бронь не найдена",
}

_QUEUE_BODIES = {
    "late": "{plate} — {checkpoint}. Вы опаздываете к своему времени в очереди.",
    "revoked": "{plate} — {checkpoint}. Ваш пропуск в очередь отозван.",
    "crossed": "{plate} — вы прошли пункт пропуска {checkpoint}.",
    "in_queue": "{plate} — {checkpoint}. Вы в очереди.",
    "check_failed": "{plate} — {checkpoint}. Проверка не пройдена, проверьте документы.",
    "none": "{plate} — {checkpoint}. В реестре бронь не найдена.",
}


def queue_status_message(status: str, *, plate: str, checkpoint: str) -> tuple[str, str]:
    """Title and body for a border-queue status change.

    An unrecognised status still produces a message rather than nothing: the
    registry can add a label at any time, and a driver being told "status
    changed" is far better than being told nothing while we wait for a deploy.
    """
    title = _QUEUE_TITLES.get(status, "🚚 Статус очереди изменился")
    template = _QUEUE_BODIES.get(status, "{plate} — {checkpoint}. Статус изменился.")
    return title, template.format(plate=plate, checkpoint=checkpoint)
