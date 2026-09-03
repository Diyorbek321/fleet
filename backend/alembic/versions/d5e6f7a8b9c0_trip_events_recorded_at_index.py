"""trip_events: index recorded_at on its own for the owner-alert trip watcher

The watcher added with the owner-alert system asks "which trips changed status
since <cutoff>" across every organization on each scheduler tick. That is a
leading filter on ``recorded_at``, and the table's only index —
``ix_trip_events_trip (trip_id, recorded_at)`` — cannot serve it, because a
composite index is only useful from its leading column inwards.

Left alone, every tick sequentially scans a table that grows with every status
change any customer ever makes: cheap on a demo tenant, and quietly the most
expensive query in the deployment a year in.

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-09-03 00:00:00.000000
"""
from alembic import op


revision = 'd5e6f7a8b9c0'
down_revision = 'c4d5e6f7a8b9'
branch_labels = None
depends_on = None

_INDEX = 'ix_trip_events_recorded_at'


def upgrade():
    op.create_index(_INDEX, 'trip_events', ['recorded_at'])


def downgrade():
    op.drop_index(_INDEX, table_name='trip_events')
