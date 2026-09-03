"""Owner-facing alerting: which Telegram chats an organization talks to, and
what has already been said to them.

Two tables, and the reason each exists:

``TelegramAccount`` is the same magic-link binding ``TripSubscription`` uses,
moved up a level: the subscriber is the company itself rather than one trip's
cargo owner. An admin mints a row, gets back a random ``token``, and opens
``t.me/<bot>?start=owner_<token>``; the webhook stamps ``chat_id``. The token is
the only thing that ever leaves the server, so nothing in the panel — and
nothing an admin can read — identifies a Telegram chat well enough to write
into it.

``NotificationLog`` is what makes the alerts survivable. The scheduler ticks
every fifteen minutes and its jobs are idempotent by design, but a *message*
is not idempotent: an overdue service interval that is still overdue would be
announced ninety-six times a day. Each row records that one real-world fact —
"this interval is overdue", "this truck burned 12% over baseline on
2026-09-02" — has already been reported, keyed so that restating the same fact
is suppressed while a genuinely new fact gets through.

The enums live here rather than in the service layer because both of them are
*stored*: ``min_severity`` is a column and ``muted_kinds`` holds ``AlertKind``
values. ``app.services.owner_alerts.bus`` re-exports them, so callers can keep
importing everything about an alert from one place.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AlertKind(str, enum.Enum):
    """What an alert is about — the unit an owner mutes.

    Muting is per kind because the kinds fail differently: an owner who does
    not want a ping for every status change still wants to hear that a driver's
    cash does not reconcile. One global on/off switch would force them to
    choose between noise and silence, and they choose silence.
    """

    trip_status = "trip_status"
    trip_delay = "trip_delay"
    leakage = "leakage"
    document_expiry = "document_expiry"
    maintenance_overdue = "maintenance_overdue"
    cash_mismatch = "cash_mismatch"
    border_queue = "border_queue"
    report_ready = "report_ready"
    briefing = "briefing"


class AlertSeverity(str, enum.Enum):
    """How loudly an alert asks to be read.

    Ordered: ``info < warning < critical``. A chat's ``min_severity`` drops
    everything below it, and ``critical`` is the one level that ignores quiet
    hours — a truck's cash going missing at 03:00 is still missing at 08:00,
    but a border closing is not.
    """

    info = "info"
    warning = "warning"
    critical = "critical"


# Rank used for the ``min_severity`` comparison. Kept as an explicit map rather
# than relying on declaration order so reordering the enum can never silently
# change which alerts an owner receives.
SEVERITY_RANK: dict[AlertSeverity, int] = {
    AlertSeverity.info: 0,
    AlertSeverity.warning: 1,
    AlertSeverity.critical: 2,
}


class TelegramAccount(Base):
    """One Telegram chat that receives an organization's owner alerts."""

    __tablename__ = "telegram_accounts"
    __table_args__ = (
        Index("ix_telegram_accounts_org", "org_id"),
        # The webhook's only lookup key: an incoming update carries a chat id
        # and nothing else.
        Index("ix_telegram_accounts_chat", "chat_id"),
        UniqueConstraint("token", name="uq_telegram_accounts_token"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )

    # Which panel user this chat belongs to, when it is known. SET NULL rather
    # than CASCADE: an owner who leaves the company should stop receiving
    # alerts by having their chat unlinked deliberately, not by having it
    # vanish the moment an admin deletes their login.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # One-time secret embedded in the deep link. The owner activates the chat
    # by sending the bot ``/start owner_<token>``.
    token: Mapped[str] = mapped_column(String(48), nullable=False)

    # Filled by the webhook on activation; NULL while the link is unopened.
    # Never serialised to the frontend — see app/routers/owner_alerts.py.
    chat_id: Mapped[str | None] = mapped_column(String(40), nullable=True)

    # Who this is, in the admin's words ("Direktor", "Buxgalter"). Purely for
    # the panel: with several chats linked, "which one do I mute" needs an
    # answer that is not a UUID.
    label: Mapped[str | None] = mapped_column(String(120), nullable=True)

    # ── Delivery preferences ────────────────────────────────────────────
    #
    # Alert fatigue is this feature's main failure mode: an owner who mutes the
    # bot in week two never comes back. So the defaults are deliberately quiet
    # — warnings and above, nothing overnight — and every knob is editable
    # from both the panel and the chat itself.

    muted_kinds: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    min_severity: Mapped[AlertSeverity] = mapped_column(
        Enum(AlertSeverity, name="alert_severity"),
        nullable=False,
        default=AlertSeverity.warning,
        server_default=AlertSeverity.warning.value,
    )

    # Local (Asia/Tashkent) hours between which non-critical alerts wait. The
    # window wraps midnight when ``from > to``, which the default 22→07 does.
    # Equal values mean "no quiet window" rather than "always quiet": the
    # degenerate reading would silence an owner permanently by accident.
    quiet_from_hour: Mapped[int | None] = mapped_column(Integer, nullable=True, default=22)
    quiet_to_hour: Mapped[int | None] = mapped_column(Integer, nullable=True, default=7)

    # False = linked but silenced. Set by the owner's /stop, by an admin in the
    # panel, and automatically when Telegram reports the chat as permanently
    # unreachable (bot blocked, chat deleted) so a dead chat is not retried
    # every fifteen minutes forever.
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )

    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )


class NotificationLog(Base):
    """One row per real-world fact already reported to an organization."""

    __tablename__ = "notification_log"
    __table_args__ = (
        # The dedupe check itself: "have we already told this org about this
        # fact". Unique so two replicas racing on the same tick cannot both
        # decide they are the first to send.
        UniqueConstraint("org_id", "dedupe_key", name="uq_notification_log_org_key"),
        # Only used by the pruning sweep — the table is append-mostly and
        # otherwise grows without bound.
        Index("ix_notification_log_sent_at", "sent_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )

    # Identity of the fact, minted by the watcher that found it — never a hash
    # of the message text. "Truck X is overdue for an oil change" must dedupe
    # against itself even after the wording changes; "truck X burned 12% over
    # baseline" must NOT dedupe against yesterday's 9%.
    dedupe_key: Mapped[str] = mapped_column(String(200), nullable=False)

    # Stored as text, not as a native enum, on purpose: each new watcher module
    # adds an AlertKind, and a native enum would make that an ALTER TYPE in a
    # migration that has to land before the watcher can ship. Severity is a
    # closed three-value set and stays a real enum.
    kind: Mapped[str] = mapped_column(String(32), nullable=False)

    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
