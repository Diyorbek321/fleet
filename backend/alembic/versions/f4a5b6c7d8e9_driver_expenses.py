"""driver expenses: daily driver-reported expenses (driver-anchored)

Revision ID: f4a5b6c7d8e9
Revises: e3f4a5b6c7d8
Create Date: 2026-06-18 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'f4a5b6c7d8e9'
down_revision = 'e3f4a5b6c7d8'
branch_labels = None
depends_on = None


expense_category = sa.Enum(
    'food', 'toll', 'parking', 'fine', 'repair', 'lodging', 'customs', 'other',
    name='expense_category',
)


def upgrade():
    # The expense_category enum is created implicitly by create_table below
    # (it is used by exactly this one table). An explicit .create() here would
    # clash with that implicit CREATE TYPE on Postgres.
    op.create_table(
        'driver_expenses',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('driver_id', sa.UUID(), nullable=False),
        sa.Column('truck_id', sa.UUID(), nullable=True),
        sa.Column('category', expense_category, nullable=False),
        sa.Column('amount', sa.Numeric(12, 2), nullable=False),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('receipt_url', sa.String(length=500), nullable=True),
        sa.Column('spent_at', sa.Date(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['driver_id'], ['drivers.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['truck_id'], ['trucks.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_driver_expenses_driver_id'), 'driver_expenses', ['driver_id'])
    op.create_index(op.f('ix_driver_expenses_spent_at'), 'driver_expenses', ['spent_at'])


def downgrade():
    bind = op.get_bind()
    op.drop_index(op.f('ix_driver_expenses_spent_at'), table_name='driver_expenses')
    op.drop_index(op.f('ix_driver_expenses_driver_id'), table_name='driver_expenses')
    op.drop_table('driver_expenses')
    expense_category.drop(bind, checkfirst=True)
