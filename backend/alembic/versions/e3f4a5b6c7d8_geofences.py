"""geofences and geofence events

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
Create Date: 2026-06-15 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'e3f4a5b6c7d8'
down_revision = 'd2e3f4a5b6c7'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'geofences',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('category', sa.String(length=40), nullable=True),
        sa.Column('center_lat', sa.Numeric(precision=10, scale=8), nullable=False),
        sa.Column('center_lng', sa.Numeric(precision=11, scale=8), nullable=False),
        sa.Column('radius_m', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'geofence_events',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('geofence_id', sa.UUID(), nullable=False),
        sa.Column('truck_id', sa.UUID(), nullable=False),
        sa.Column('event', sa.Enum('enter', 'exit', name='geofence_event_type'), nullable=False),
        sa.Column('latitude', sa.Numeric(precision=10, scale=8), nullable=False),
        sa.Column('longitude', sa.Numeric(precision=11, scale=8), nullable=False),
        sa.Column('recorded_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['geofence_id'], ['geofences.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['truck_id'], ['trucks.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_geofence_events_truck_geofence',
        'geofence_events',
        ['truck_id', 'geofence_id', 'recorded_at'],
    )


def downgrade():
    op.drop_index('ix_geofence_events_truck_geofence', table_name='geofence_events')
    op.drop_table('geofence_events')
    op.drop_table('geofences')
    sa.Enum(name='geofence_event_type').drop(op.get_bind(), checkfirst=True)
