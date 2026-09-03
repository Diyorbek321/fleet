"""The owner's side of the Telegram conversation.

The webhook owns transport and authenticity; this module owns *meaning*. Given
a chat id and whatever the owner typed, it returns the text to reply with, or
``None`` when the message is not this module's business — which is how a chat
that is also a cargo-owner trip subscriber keeps working: an unrecognised chat
falls straight through to the existing ``TripSubscription`` handling.

**Extension contract.** A later agent adds free-text questions ("bu oy qancha
sarfladik?") to this same chat. It must not edit ``handle_owner_message``.
Instead:

* ``register_command("/mute", handler)`` adds a slash command;
* ``register_fallback(handler)`` adds a handler for anything that is not a
  slash command. Fallbacks run in registration order and the first one to
  return a string wins, so a narrow matcher registered early can claim its
  phrasing and leave the rest alone. ``app.services.owner_alerts.ask`` — the
  free-text answering agent — is loaded on first use by ``_ensure_fallbacks``.

Both handler kinds receive ``(db, accounts, argument)`` where ``accounts`` is
every owner chat row bound to this Telegram chat — normally one, more when the
same person owns two companies — and must never raise; the webhook swallows
exceptions, so a crash here reads to the owner as silence.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import logger
from app.models.organizations import Organization
from app.models.owner_alerts import AlertKind, AlertSeverity, TelegramAccount

# The deep-link namespace. ``trip_`` already belongs to cargo-owner trip
# subscriptions on the same bot, so owner links carry their own prefix and the
# webhook can tell the two flows apart from the payload alone.
OWNER_TOKEN_PREFIX = "owner_"

CommandHandler = Callable[[AsyncSession, list[TelegramAccount], str], Awaitable[str]]
FallbackHandler = Callable[[AsyncSession, list[TelegramAccount], str], Awaitable[str | None]]


# ── Link plumbing ────────────────────────────────────────────────────────


def build_owner_deep_link(token: str) -> str:
    """The magic link an admin shows the owner.

    Falls back to a ``tg://`` URL when the bot username is unconfigured, so the
    link is still copy-pasteable: the owner opens Telegram, finds the bot and
    sends ``/start owner_<token>`` by hand.
    """
    username = settings.telegram_bot_username.strip().lstrip("@")
    if username:
        return f"https://t.me/{username}?start={OWNER_TOKEN_PREFIX}{token}"
    return f"tg://resolve?start={OWNER_TOKEN_PREFIX}{token}"


def parse_owner_start(text: str) -> str | None:
    """Return the account token from ``/start owner_<token>``, else ``None``.

    Rejects anything that could not have been minted by ``secrets.token_urlsafe``
    so an obviously bogus payload costs no database round-trip.
    """
    if not text:
        return None
    parts = text.strip().split(maxsplit=1)
    if len(parts) != 2 or parts[0].split("@", 1)[0] != "/start":
        return None
    payload = parts[1].strip()
    if not payload.startswith(OWNER_TOKEN_PREFIX):
        return None
    token = payload[len(OWNER_TOKEN_PREFIX):]
    if not token or len(token) > 48 or not all(c.isalnum() or c in "-_" for c in token):
        return None
    return token


# ── Uzbek labels ─────────────────────────────────────────────────────────

_KIND_LABEL_UZ: dict[AlertKind, str] = {
    AlertKind.trip_status: "Reys holati",
    AlertKind.trip_delay: "Reys kechikishi",
    AlertKind.leakage: "Yo'qotishlar",
    AlertKind.document_expiry: "Hujjat muddati",
    AlertKind.maintenance_overdue: "Texnik xizmat",
    AlertKind.cash_mismatch: "Kassa farqi",
    AlertKind.border_queue: "Chegara navbati",
    AlertKind.report_ready: "Hisobotlar",
    AlertKind.briefing: "Kunlik xulosa",
}

_SEVERITY_LABEL_UZ: dict[AlertSeverity, str] = {
    AlertSeverity.info: "hammasi",
    AlertSeverity.warning: "ogohlantirish va muhim",
    AlertSeverity.critical: "faqat muhim",
}

_HELP_TEXT = (
    "🤖 <b>Buyruqlar</b>\n"
    "/settings — joriy sozlamalar\n"
    "/stop — xabarlarni to'xtatish\n"
    "/help — shu ro'yxat\n\n"
    "Sozlamalarni panelda o'zgartirasiz: <i>Sozlamalar → Telegram</i>."
)


# ── Activation ───────────────────────────────────────────────────────────


async def activate_owner_chat(
    db: AsyncSession, token: str, chat_id: str, username: str | None = None
) -> str:
    """Bind an incoming chat to the account row identified by ``token``.

    Idempotent: re-opening the same link from the same chat re-confirms rather
    than erroring, because owners do re-tap a link they were sent twice.
    Re-opening it from a *different* chat moves the binding — the link is the
    credential, and the admin who minted it decides who gets it.
    """
    account = (
        await db.execute(select(TelegramAccount).where(TelegramAccount.token == token))
    ).scalar_one_or_none()
    if account is None:
        return "❌ Havola noto'g'ri yoki eskirgan. Administratordan yangisini so'rang."

    account.chat_id = chat_id
    account.activated_at = account.activated_at or datetime.now(timezone.utc)
    # An owner who blocked the bot and came back through the same link is
    # re-enabling delivery; that is the only way to undo an automatic
    # deactivation without an admin touching the panel.
    account.is_active = True
    if username and not account.label:
        account.label = username[:120]
    await db.commit()

    org = (
        await db.execute(select(Organization).where(Organization.id == account.org_id))
    ).scalar_one_or_none()
    org_name = org.name if org else "kompaniya"
    return (
        f"✅ Ulandi — <b>{org_name}</b>.\n\n"
        "Endi muhim voqealar haqida shu chatga xabar keladi: reys holati, "
        "yo'qotishlar, hujjat muddati, kassa farqi va hisobotlar.\n\n"
        + _HELP_TEXT
    )


# ── Commands ─────────────────────────────────────────────────────────────


async def _cmd_help(_db: AsyncSession, _accounts: list[TelegramAccount], _arg: str) -> str:
    return _HELP_TEXT


async def _cmd_start(_db: AsyncSession, accounts: list[TelegramAccount], _arg: str) -> str:
    """Bare ``/start`` from a chat that is already linked."""
    live = [a for a in accounts if a.is_active]
    if not live:
        return (
            "⏸ Xabarlar hozir o'chirilgan. Qayta yoqish uchun administratordan "
            "yangi havola so'rang."
        )
    return _HELP_TEXT


async def _cmd_stop(db: AsyncSession, accounts: list[TelegramAccount], _arg: str) -> str:
    """Silence every owner link on this chat.

    Deactivates rather than deletes: the admin panel must keep showing that
    this person switched the alerts off, otherwise the row simply disappears
    and nobody can explain why the director stopped hearing about anything.
    """
    for account in accounts:
        account.is_active = False
    await db.commit()
    return (
        "🛑 Xabarlar to'xtatildi. Qayta yoqish uchun administratordan yangi havola so'rang."
    )


async def _cmd_settings(_db: AsyncSession, accounts: list[TelegramAccount], _arg: str) -> str:
    lines = ["⚙️ <b>Sozlamalar</b>"]
    for account in accounts:
        name = account.label or "chat"
        state = "yoqilgan" if account.is_active else "o'chirilgan"
        lines.append(f"\n• <b>{name}</b> — {state}")
        lines.append(f"  Daraja: {_SEVERITY_LABEL_UZ.get(account.min_severity, '—')}")
        known = {m.value for m in AlertKind}
        muted = [
            _KIND_LABEL_UZ[AlertKind(k)] for k in (account.muted_kinds or []) if k in known
        ]
        lines.append("  O'chirilgan turlar: " + (", ".join(muted) if muted else "yo'q"))
        if account.quiet_from_hour is not None and account.quiet_to_hour is not None:
            lines.append(
                f"  Tungi tinchlik: {account.quiet_from_hour:02d}:00–"
                f"{account.quiet_to_hour:02d}:00"
            )
    lines.append("\nO'zgartirish: panel → <i>Sozlamalar → Telegram</i>, yoki /stop.")
    return "\n".join(lines)


# Dispatch table. Mutable by design — see the module docstring's extension
# contract; a later agent registers into it instead of editing the dispatcher.
_COMMANDS: dict[str, CommandHandler] = {
    "/start": _cmd_start,
    "/stop": _cmd_stop,
    "/settings": _cmd_settings,
    "/help": _cmd_help,
}

_FALLBACKS: list[FallbackHandler] = []


def register_command(name: str, handler: CommandHandler) -> None:
    """Add (or replace) a slash command. ``name`` includes the leading slash."""
    _COMMANDS[name.lower()] = handler


def register_fallback(handler: FallbackHandler) -> None:
    """Add a handler for non-command text. First non-None reply wins."""
    _FALLBACKS.append(handler)


_EXTENSIONS_LOADED = False


def _ensure_fallbacks() -> list[FallbackHandler]:
    """Import the modules that register themselves, then hand back the handlers.

    Deferred rather than imported at the top of this file: ``ask`` registers
    itself *by importing this module*, so an eager import here is a cycle. It is
    also swallowed on failure — a broken extension must cost the owner their
    free-text answer, not the /settings command sitting next to it.
    """
    global _EXTENSIONS_LOADED
    if not _EXTENSIONS_LOADED:
        _EXTENSIONS_LOADED = True
        try:
            from app.services.owner_alerts import ask  # noqa: F401
        except Exception:  # noqa: BLE001
            logger.exception("owner_fallback_import_failed")
    return _FALLBACKS


def _split_command(text: str) -> tuple[str, str]:
    """``"/settings@FleetBot xyz"`` → ``("/settings", "xyz")``.

    Telegram appends ``@botname`` to commands sent in groups; stripping it here
    means every handler sees the same key whether the owner wrote from a private
    chat or a company group.
    """
    stripped = text.strip()
    head, _, rest = stripped.partition(" ")
    return head.split("@", 1)[0].lower(), rest.strip()


async def handle_owner_message(db: AsyncSession, chat_id: str, text: str) -> str | None:
    """Reply text for an owner-chat message, or ``None`` if not ours to answer.

    ``None`` is returned when the chat has no owner link at all, so the webhook
    can fall through to the cargo-owner trip flow it shares this bot with.
    """
    accounts = (
        await db.execute(select(TelegramAccount).where(TelegramAccount.chat_id == chat_id))
    ).scalars().all()
    if not accounts:
        return None

    accounts = list(accounts)
    command, argument = _split_command(text)
    handler = _COMMANDS.get(command)
    if handler is not None:
        return await handler(db, accounts, argument)

    for fallback in _ensure_fallbacks():
        reply = await fallback(db, accounts, text.strip())
        if reply is not None:
            return reply

    return _HELP_TEXT
