"""trip segments: moving/stopped segmentation of a trip's GPS history

Revision ID: b6c7d8e9f0a1
Revises: a5b6c7d8e9f0
Create Date: 2026-06-24 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'b6c7d8e9f0a1'
down_revision = 'a5b6c7d8e9f0'
branch_labels = None
depends_on = None


# segment_kind is used by exactly this one table, so it is created implicitly by
# create_table (an explicit .create() would clash with the implicit CREATE TYPE
# on Postgres — same pattern as the driver_expenses migration).
segment_kind = sa.Enum('moving', 'stopped', name='segment_kind')


def upgrade():
    op.create_table(
        'trip_segments',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('trip_id', sa.UUID(), nullable=False),
        sa.Column('seq', sa.Integer(), nullable=False),
        sa.Column('kind', segment_kind, nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('ended_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('duration_s', sa.Integer(), nullable=False),
        sa.Column('start_lat', sa.Numeric(precision=10, scale=8), nullable=True),
        sa.Column('start_lng', sa.Numeric(precision=11, scale=8), nullable=True),
        sa.Column('end_lat', sa.Numeric(precision=10, scale=8), nullable=True),
        sa.Column('end_lng', sa.Numeric(precision=11, scale=8), nullable=True),
        sa.Column('distance_km', sa.Numeric(precision=10, scale=3), nullable=False),
        sa.Column('point_count', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['trip_id'], ['trips.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_trip_segments_trip', 'trip_segments', ['trip_id', 'seq'])


def downgrade():
    op.drop_index('ix_trip_segments_trip', table_name='trip_segments')
    op.drop_table('trip_segments')
    segment_kind.drop(op.get_bind(), checkfirst=True)
