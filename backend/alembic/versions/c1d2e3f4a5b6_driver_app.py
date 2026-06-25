"""driver app: driver role, user-driver link, shifts, maintenance requests, push tokens

Revision ID: c1d2e3f4a5b6
Revises: a289700a458c
Create Date: 2026-06-14 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'c1d2e3f4a5b6'
down_revision = 'a289700a458c'
branch_labels = None
depends_on = None


shift_status = sa.Enum('active', 'ended', name='shift_status')
mr_status = sa.Enum('open', 'acknowledged', 'resolved', name='maintenance_request_status')


def upgrade():
    bind = op.get_bind()

    # 1. Add 'driver' to the user_role enum (Postgres only; SQLite stores as VARCHAR).
    if bind.dialect.name == 'postgresql':
        op.execute("ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'driver'")

    # 2. Link a user to a driver profile. Use batch mode so SQLite (which has no
    # ALTER-constraint support) rebuilds the table; on Postgres these emit plain
    # ALTER TABLE statements.
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('driver_id', sa.UUID(), nullable=True))
        batch_op.create_unique_constraint('uq_users_driver_id', ['driver_id'])
        batch_op.create_foreign_key(
            'fk_users_driver_id', 'drivers', ['driver_id'], ['id'], ondelete='SET NULL'
        )

    # 3. New tables. The enum types are created implicitly by create_table
    # below (each type is used by exactly one table). On Postgres an explicit
    # .create() here would clash with that implicit CREATE TYPE; on SQLite
    # enums are plain VARCHAR, so nothing extra is needed.
    op.create_table(
        'shifts',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('driver_id', sa.UUID(), nullable=False),
        sa.Column('truck_id', sa.UUID(), nullable=True),
        sa.Column('status', shift_status, nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('start_mileage', sa.Numeric(12, 2), nullable=True),
        sa.Column('end_mileage', sa.Numeric(12, 2), nullable=True),
        sa.ForeignKeyConstraint(['driver_id'], ['drivers.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['truck_id'], ['trucks.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_shifts_driver_id'), 'shifts', ['driver_id'])

    op.create_table(
        'maintenance_requests',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('driver_id', sa.UUID(), nullable=True),
        sa.Column('truck_id', sa.UUID(), nullable=True),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('photo_url', sa.String(length=500), nullable=True),
        sa.Column('status', mr_status, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['driver_id'], ['drivers.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['truck_id'], ['trucks.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'push_tokens',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('token', sa.String(length=512), nullable=False),
        sa.Column('platform', sa.String(length=20), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('token', name='uq_push_tokens_token'),
    )
    op.create_index(op.f('ix_push_tokens_user_id'), 'push_tokens', ['user_id'])


def downgrade():
    bind = op.get_bind()

    op.drop_index(op.f('ix_push_tokens_user_id'), table_name='push_tokens')
    op.drop_table('push_tokens')
    op.drop_table('maintenance_requests')
    op.drop_index(op.f('ix_shifts_driver_id'), table_name='shifts')
    op.drop_table('shifts')

    mr_status.drop(bind, checkfirst=True)
    shift_status.drop(bind, checkfirst=True)

    # Dropping the column also removes the single-column unique + FK constraints
    # that depend on it (Postgres drops them automatically; SQLite rebuilds the
    # table without them via batch mode).
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('driver_id')
    # Note: Postgres cannot easily DROP a value from an enum; 'driver' is left in user_role.
