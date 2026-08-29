"""Per-org trip references + an index the GPS retention purge can use.

Two independent production defects, one revision because both are pure DDL on
tables that must not be touched twice.

1. ``trips.reference`` was globally unique. Trip numbers are generated
   sequentially, so with a shared namespace a new customer's very first trip is
   numbered from the platform-wide total (leaking how much freight the other
   tenants move), and two organizations creating a trip in the same moment
   collide on a reference neither of them can see. Uniqueness belongs per
   tenant: ``(org_id, reference)``. Every existing row satisfies the new
   constraint trivially, since the old one was stricter.

2. ``truck_location_history`` had no index on ``recorded_at`` alone. The new
   retention job deletes by age, and the existing composite index leads with
   ``truck_id``, so the purge would sequentially scan the largest table in the
   database on every run.

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-08-17
"""
from __future__ import annotations

from alembic import op

revision = 'e5f6a7b8c9d0'
down_revision = 'd4e5f6a7b8c9'
branch_labels = None
depends_on = None


# Postgres derives this name from `sa.UniqueConstraint('reference')` in the
# original create_table (revision a5b6c7d8e9f0).
_OLD_UNIQUE = 'trips_reference_key'
_NEW_UNIQUE = 'uq_trips_org_reference'
_HISTORY_INDEX = 'ix_truck_location_history_recorded_at'


def upgrade() -> None:
    # Guarded rather than a bare op.drop_constraint: production has drifted from
    # the migration chain before (see revision d4e5f6a7b8c9), and a hand-repaired
    # database may not carry the auto-generated name. Missing is fine — the goal
    # is "no global unique constraint", not "this exact DROP succeeded".
    op.execute(f'ALTER TABLE trips DROP CONSTRAINT IF EXISTS "{_OLD_UNIQUE}"')
    op.execute(
        f'ALTER TABLE trips ADD CONSTRAINT "{_NEW_UNIQUE}" UNIQUE (org_id, reference)'
    )

    # CONCURRENTLY so building the index never blocks position writes: this table
    # is the hot ingest path and is already the biggest one in the database.
    # It cannot run inside a transaction, hence the autocommit block.
    with op.get_context().autocommit_block():
        op.execute(
            f'CREATE INDEX CONCURRENTLY IF NOT EXISTS "{_HISTORY_INDEX}" '
            'ON truck_location_history (recorded_at)'
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f'DROP INDEX CONCURRENTLY IF EXISTS "{_HISTORY_INDEX}"')

    op.execute(f'ALTER TABLE trips DROP CONSTRAINT IF EXISTS "{_NEW_UNIQUE}"')
    # Restoring global uniqueness can genuinely fail if two tenants have since
    # taken the same reference — which is the whole point of the upgrade. Left
    # unguarded on purpose so a downgrade that would corrupt data stops loudly.
    op.execute(f'ALTER TABLE trips ADD CONSTRAINT "{_OLD_UNIQUE}" UNIQUE (reference)')
