"""trips, trip events, and trip links on fuel/expenses

Revision ID: a5b6c7d8e9f0
Revises: f4a5b6c7d8e9
Create Date: 2026-06-19 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = 'a5b6c7d8e9f0'
down_revision = 'f4a5b6c7d8e9'
branch_labels = None
depends_on = None


# trip_status is shared by trips.status and trip_events.from/to_status, so the
# Postgres enum type is created once explicitly and referenced with
# create_type=False on every column. NOTE: generic sa.Enum silently ignores
# create_type, so postgresql.ENUM must be used for the suppression to take
# effect — otherwise each column re-emits CREATE TYPE and Postgres errors with
# "type already exists".
trip_status = postgresql.ENUM(
    'draft', 'planned', 'loading', 'en_route', 'at_border', 'delivered', 'cancelled',
    name='trip_status',
    create_type=False,
)
trip_event_type = postgresql.ENUM(
    'created', 'status_change', 'note', 'border_arrival', 'border_clear', 'pod',
    name='trip_event_type',
    create_type=False,
)


def upgrade():
    bind = op.get_bind()
    trip_status.create(bind, checkfirst=True)
    trip_event_type.create(bind, checkfirst=True)

    status_col = postgresql.ENUM(name='trip_status', create_type=False)
    event_col = postgresql.ENUM(name='trip_event_type', create_type=False)

    op.create_table(
        'trips',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('reference', sa.String(length=40), nullable=False),
        sa.Column('truck_id', sa.UUID(), nullable=True),
        sa.Column('driver_id', sa.UUID(), nullable=True),
        sa.Column('status', status_col, nullable=False),
        sa.Column('shipper', sa.String(length=200), nullable=True),
        sa.Column('consignee', sa.String(length=200), nullable=True),
        sa.Column('origin_name', sa.String(length=200), nullable=True),
        sa.Column('origin_lat', sa.Numeric(precision=10, scale=8), nullable=True),
        sa.Column('origin_lng', sa.Numeric(precision=11, scale=8), nullable=True),
        sa.Column('destination_name', sa.String(length=200), nullable=True),
        sa.Column('destination_lat', sa.Numeric(precision=10, scale=8), nullable=True),
        sa.Column('destination_lng', sa.Numeric(precision=11, scale=8), nullable=True),
        sa.Column('cargo_description', sa.String(length=255), nullable=True),
        sa.Column('cargo_weight_kg', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('is_reefer', sa.Boolean(), nullable=False),
        sa.Column('rate', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('currency', sa.String(length=3), nullable=False),
        sa.Column('planned_distance_km', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('scheduled_start', sa.DateTime(timezone=True), nullable=True),
        sa.Column('scheduled_end', sa.DateTime(timezone=True), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('delivered_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['truck_id'], ['trucks.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['driver_id'], ['drivers.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('reference'),
    )
    op.create_index('ix_trips_status', 'trips', ['status'])
    op.create_index('ix_trips_truck', 'trips', ['truck_id'])

    op.create_table(
        'trip_events',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('trip_id', sa.UUID(), nullable=False),
        sa.Column('event', event_col, nullable=False),
        sa.Column('from_status', postgresql.ENUM(name='trip_status', create_type=False), nullable=True),
        sa.Column('to_status', postgresql.ENUM(name='trip_status', create_type=False), nullable=True),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('latitude', sa.Numeric(precision=10, scale=8), nullable=True),
        sa.Column('longitude', sa.Numeric(precision=11, scale=8), nullable=True),
        sa.Column('recorded_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['trip_id'], ['trips.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_trip_events_trip', 'trip_events', ['trip_id', 'recorded_at'])

    # Batch mode so SQLite can add the FK (it has no ALTER-constraint support);
    # on Postgres these emit plain ALTER TABLE statements.
    with op.batch_alter_table('fuel_logs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('trip_id', sa.UUID(), nullable=True))
        batch_op.create_foreign_key('fk_fuel_logs_trip', 'trips', ['trip_id'], ['id'], ondelete='SET NULL')

    with op.batch_alter_table('driver_expenses', schema=None) as batch_op:
        batch_op.add_column(sa.Column('trip_id', sa.UUID(), nullable=True))
        batch_op.create_foreign_key('fk_driver_expenses_trip', 'trips', ['trip_id'], ['id'], ondelete='SET NULL')


def downgrade():
    # Dropping the column removes its dependent FK (Postgres drops it
    # automatically; SQLite rebuilds the table without it via batch mode).
    with op.batch_alter_table('driver_expenses', schema=None) as batch_op:
        batch_op.drop_column('trip_id')
    with op.batch_alter_table('fuel_logs', schema=None) as batch_op:
        batch_op.drop_column('trip_id')

    op.drop_index('ix_trip_events_trip', table_name='trip_events')
    op.drop_table('trip_events')
    op.drop_index('ix_trips_truck', table_name='trips')
    op.drop_index('ix_trips_status', table_name='trips')
    op.drop_table('trips')

    sa.Enum(name='trip_event_type').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='trip_status').drop(op.get_bind(), checkfirst=True)
