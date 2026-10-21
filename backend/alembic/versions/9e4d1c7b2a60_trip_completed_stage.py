"""The "trip completed" checkpoint.

``unloaded`` no longer closes a trip; ``trip_completed`` does. Only the enum
grows here — the stage → status mapping lives in code.

Revision ID: 9e4d1c7b2a60
Revises: b8d2f0e4a6c1
"""
from alembic import op

revision = "9e4d1c7b2a60"
down_revision = "b8d2f0e4a6c1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Postgres 12+ allows ADD VALUE inside the migration's transaction; the
    # label is not used until the next one. SQLite stores enums as VARCHAR.
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TYPE trip_stage ADD VALUE IF NOT EXISTS 'trip_completed' AFTER 'unloaded'")


def downgrade() -> None:
    # Postgres cannot drop an enum label; a stray value is harmless.
    pass
