"""Repair production drift: trip_subscriptions.updated_at

This column is already created by ``e9f0a1b2c3d4_trip_subscriptions.py`` (the
``op.create_table`` that introduced the table), so on any database built from
this migration chain there is nothing to do here and this revision is a no-op.

The production database is not such a database. It reports ``alembic_current ==
head`` yet has no ``updated_at`` column — the schema diverged from the chain,
most likely because images are built from a developer working tree rather than
a clean checkout, so an earlier draft of the create_table ran there. The effect
was severe and completely silent: every SELECT on ``trip_subscriptions`` raised
``UndefinedColumnError``, and both call sites swallow their exceptions, so the
whole Telegram feature (daily "where is my cargo" digest, trip status pushes,
and ``/start`` deep-link activation) was dead for over a week with no user-
visible error — only a ``daily_trip_updates_failed`` line every 15 minutes.

Hence ``ADD COLUMN IF NOT EXISTS``: a plain ``op.add_column`` would repair
production but fail with ``DuplicateColumnError`` on every correctly-migrated
environment, including CI and the test suite. Doing it as a migration rather
than a hand-run ALTER means the repair travels through the normal deploy path
and is recorded, reviewable, and repeatable.

The NOT NULL needs a ``server_default``; production already holds subscription
rows, and without one the ALTER cannot fill them.

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
"""
from alembic import op


revision = 'd4e5f6a7b8c9'
down_revision = 'c3d4e5f6a7b8'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "ALTER TABLE trip_subscriptions "
        "ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now()"
    )


def downgrade():
    # Deliberately a no-op. The column belongs to revision e9f0a1b2c3d4, which
    # owns dropping it; removing it here would leave a correctly-migrated
    # database missing a column its own create_table declared.
    pass
