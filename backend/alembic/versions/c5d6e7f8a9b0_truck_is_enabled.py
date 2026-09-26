"""A truck being off the air is not the same as a truck being off the board.

``trucks.status`` answers "what did the tracker last say"; ``offline`` is the
ordinary state of a rig in a tunnel, at a border crossing, or not yet fitted
with a device. The panel was reading that column as "switched off" as well,
which meant a truck was born disabled — a new record has no GPS, so it came out
``offline``, so the map, the fuel picker and the service picker all filtered it
away until some first ping happened to arrive.

So the decision gets a column of its own.

Backfill is ``true`` for every existing row rather than ``status != 'offline'``.
The old data cannot tell the two apart, and of the two ways to be wrong, one
shows a parked truck on the map until someone clicks Disable, while the other
hides most of a fleet — at any moment a large share of trucks are legitimately
out of coverage — and gives no clue why.

Revision ID: c5d6e7f8a9b0
Revises: b1c2d3e4f5a6
"""
from alembic import op
import sqlalchemy as sa

revision = "c5d6e7f8a9b0"
down_revision = "b1c2d3e4f5a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # server_default so NOT NULL can be added to a populated table in one pass.
    # It stays on the column afterwards: the ORM supplies the value on every
    # insert, but a truck created by a migration, a seed script or a hand-run
    # INSERT should be in service too.
    op.add_column(
        "trucks",
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    op.drop_column("trucks", "is_enabled")
