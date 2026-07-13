"""trip_subscriptions: Telegram/customer notification subscription per trip

Creates the ``trip_subscriptions`` table. Each row binds one trip to one
Telegram chat (populated when the cargo owner opens the bot's deep link) so
the scheduler can push daily location updates and status-change events
without the cargo owner needing an account.

Revision ID: e9f0a1b2c3d4
Revises: d8e9f0a1b2c3
Create Date: 2026-07-04 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'e9f0a1b2c3d4'
down_revision = 'd8e9f0a1b2c3'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'trip_subscriptions',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('org_id', sa.UUID(), nullable=False),
        sa.Column('trip_id', sa.UUID(), nullable=False),
        sa.Column('token', sa.String(length=48), nullable=False),
        sa.Column('contact_name', sa.String(length=200), nullable=True),
        sa.Column('contact_phone', sa.String(length=40), nullable=True),
        sa.Column('chat_id', sa.String(length=40), nullable=True),
        sa.Column('language', sa.String(length=10), nullable=True),
        sa.Column('username', sa.String(length=80), nullable=True),
        sa.Column('daily_enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('event_enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('activated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_daily_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['trip_id'], ['trips.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('token', name='uq_trip_subscriptions_token'),
    )
    op.create_index('ix_trip_subscriptions_org_id', 'trip_subscriptions', ['org_id'])
    op.create_index('ix_trip_subscriptions_trip', 'trip_subscriptions', ['trip_id'])
    op.create_index('ix_trip_subscriptions_chat', 'trip_subscriptions', ['chat_id'])


def downgrade():
    op.drop_index('ix_trip_subscriptions_chat', table_name='trip_subscriptions')
    op.drop_index('ix_trip_subscriptions_trip', table_name='trip_subscriptions')
    op.drop_index('ix_trip_subscriptions_org_id', table_name='trip_subscriptions')
    op.drop_table('trip_subscriptions')
