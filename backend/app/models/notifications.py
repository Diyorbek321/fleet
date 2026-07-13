"""Customer-facing notification subscriptions.

A ``TripSubscription`` binds a Telegram (or future channel) chat to exactly
one trip so the cargo owner receives progress updates without needing an
account in the fleet system.

Flow:

1. Dispatcher creates the subscription for a trip (contact name + phone). A
   random ``token`` is generated and shown to the dispatcher as a magic link
   like ``t.me/<bot>?start=trip_<token>``.
2. Cargo owner opens the link → Telegram sends the bot ``/start trip_<token>``
   → the webhook looks up the row by token and stamps ``chat_id`` +
   ``activated_at``. From that moment on the daily / event pushes go out to
   that chat.
3. On trip delivery the scheduler stops targeting the row (``daily_enabled``
   is honoured, and status filters exclude ``delivered``).

Only the token leaves the server. ``chat_id`` is populated by the webhook and
is never handed to the frontend, so the dispatcher can't hijack the chat.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class TripSubscription(Base):
    """A cargo owner's subscription to daily / event updates for one trip."""

    __tablename__ = "trip_subscriptions"
    __table_args__ = (
        Index("ix_trip_subscriptions_trip", "trip_id"),
        Index("ix_trip_subscriptions_chat", "chat_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    trip_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("trips.id", ondelete="CASCADE"), nullable=False
    )

    # One-time secret embedded in the Telegram deep link. The cargo owner
    # activates the subscription by sending ``/start trip_<token>`` to the bot.
    token: Mapped[str] = mapped_column(String(48), unique=True, nullable=False)

    # Contact info captured from the dispatcher when the subscription is created.
    contact_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(40), nullable=True)

    # Telegram chat id — filled by the webhook when the user opens the link.
    # NULL while the subscription is "pending" (link generated but not yet
    # opened).
    chat_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # Telegram language code / username, best-effort, purely informational.
    language: Mapped[str | None] = mapped_column(String(10), nullable=True)
    username: Mapped[str | None] = mapped_column(String(80), nullable=True)

    # Owner-controlled toggles. Default both on so activation immediately
    # produces useful traffic; the /settings command in the bot flips them.
    daily_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    event_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_daily_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
