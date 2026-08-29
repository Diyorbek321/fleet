"""Push delivery to drivers' phones, via Expo.

The mobile app is an Expo build, so its devices are addressed by Expo push
tokens and delivery goes through Expo's own service. That is deliberate: the
alternative is registering an FCM sender and an APNs key and shipping both sets
of credentials to the server, which is a lot of setup to notify a handful of
drivers that their border slot moved.

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
    skipped = len(tokens) - len(deliverable)
    if skipped:
        logger.warning(
            "push_tokens_skipped_wrong_format",
            skipped=skipped,
            hint="only Expo-format tokens can be delivered through Expo",
        )
    if not deliverable:
        return PushOutcome(skipped=skipped)

    accepted = 0
    failed = 0
    removed: list[str] = []

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
# Uzbek, matching the customer-facing Telegram messages in
# ``app/services/telegram.py``. The driver app is translated, but a push
# notification is rendered by the OS from what the server sends, and the server
# has no record of which language a driver picked — so this follows the same
# choice the rest of the platform's outbound text already makes.

_QUEUE_TITLES = {
    "late": "⏰ Navbatga kechikyapsiz",
    "revoked": "❌ Ruxsat bekor qilindi",
    "crossed": "✅ Chegaradan o'tdingiz",
    "in_queue": "🕓 Navbatdasiz",
    "check_failed": "⚠️ Tekshiruv o'tmadi",
    "none": "ℹ️ Bronь topilmadi",
}

_QUEUE_BODIES = {
    "late": "{plate} — {checkpoint}. Navbat vaqtingizdan kechikyapsiz.",
    "revoked": "{plate} — {checkpoint}. Navbat ruxsatingiz bekor qilindi.",
    "crossed": "{plate} — {checkpoint} chegara punktidan o'tdingiz.",
    "in_queue": "{plate} — {checkpoint}. Navbatdasiz.",
    "check_failed": "{plate} — {checkpoint}. Tekshiruv o'tmadi, hujjatlarni qayta ko'ring.",
    "none": "{plate} — {checkpoint}. Registrda bron topilmadi.",
}


def queue_status_message(status: str, *, plate: str, checkpoint: str) -> tuple[str, str]:
    """Title and body for a border-queue status change.

    An unrecognised status still produces a message rather than nothing: the
    registry can add a label at any time, and a driver being told "status
    changed" is far better than being told nothing while we wait for a deploy.
    """
    title = _QUEUE_TITLES.get(status, "🚚 Navbat holati o'zgardi")
    template = _QUEUE_BODIES.get(status, "{plate} — {checkpoint}. Holat o'zgardi.")
    return title, template.format(plate=plate, checkpoint=checkpoint)
