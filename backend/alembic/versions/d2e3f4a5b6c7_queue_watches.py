"""queue watches for CarGoRuqsat border-queue tracking

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
Create Date: 2026-06-14 00:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'd2e3f4a5b6c7'
down_revision = 'c1d2e3f4a5b6'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'queue_watches',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('driver_id', sa.UUID(), nullable=False),
        sa.Column('plate', sa.String(length=20), nullable=False),
        sa.Column('checkpoint', sa.String(length=200), nullable=False),
        sa.Column('country', sa.String(length=100), nullable=True),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('last_status', sa.String(length=40), nullable=True),
        sa.Column('last_notified_status', sa.String(length=40), nullable=True),
        sa.Column('last_seen_queue_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['driver_id'], ['drivers.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('driver_id', 'country', name='uq_queue_watch_driver_country'),
    )
    op.create_index(op.f('ix_queue_watches_driver_id'), 'queue_watches', ['driver_id'])


def downgrade():
    op.drop_index(op.f('ix_queue_watches_driver_id'), table_name='queue_watches')
    op.drop_table('queue_watches')
