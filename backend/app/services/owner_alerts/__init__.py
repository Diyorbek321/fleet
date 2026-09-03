"""Owner alerting: one gated path to an owner's Telegram, plus the watchers on it.

Import everything an alert needs from here rather than reaching into the
submodules — ``bus`` may split as more delivery channels appear, and the names
below are the stable surface eight watcher modules code against.

Each watcher module in this package exposes exactly one entry point::

    async def run(db: AsyncSession) -> int:
        \"\"\"Evaluate this signal across every organization and notify.\"\"\"

It iterates organizations itself, is idempotent, and never raises — the
scheduler tick that calls it must survive whatever it finds.
"""
from app.models.owner_alerts import AlertKind, AlertSeverity, NotificationLog, TelegramAccount
from app.services.owner_alerts.bus import (
    Alert,
    notify_owner,
    prune_notification_log,
    render_alert,
    send_owner_document,
)
from app.services.owner_alerts.commands import (
    OWNER_TOKEN_PREFIX,
    activate_owner_chat,
    build_owner_deep_link,
    handle_owner_message,
    parse_owner_start,
    register_command,
    register_fallback,
)

__all__ = [
    "Alert",
    "AlertKind",
    "AlertSeverity",
    "NotificationLog",
    "TelegramAccount",
    "OWNER_TOKEN_PREFIX",
    "activate_owner_chat",
    "build_owner_deep_link",
    "handle_owner_message",
    "notify_owner",
    "parse_owner_start",
    "prune_notification_log",
    "register_command",
    "register_fallback",
    "render_alert",
    "send_owner_document",
]
