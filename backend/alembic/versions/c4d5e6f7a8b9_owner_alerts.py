"""owner alerts: linked owner Telegram chats + the dedupe ledger behind them

``telegram_accounts`` binds an organization to the chats that receive its owner
alerts, using the same magic-link shape as ``trip_subscriptions``: a random
token is the only thing that leaves the server and the webhook stamps
``chat_id``.

``notification_log`` is what makes those alerts survivable. The scheduler ticks
every fifteen minutes, so without a record of which real-world facts have
already been reported an overdue service interval would be announced ninety-six
times a day. The unique constraint on (org_id, dedupe_key) is load-bearing: it
is also what stops two replicas on the same tick from both deciding they are
the first to send.

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
Create Date: 2026-09-03 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = 'c4d5e6f7a8b9'
down_revision = 'b3c4d5e6f7a8'
branch_labels = None
depends_on = None


# Severity is a closed three-value set, so it is a real enum type. Alert *kind*
# deliberately is not: every new watcher module adds one, and a native enum
# would make each of those an ALTER TYPE that has to land before the watcher
# can ship. Kinds are stored as text in ``notification_log.kind`` and inside
# the ``muted_kinds`` JSON array.
alert_severity = sa.Enum('info', 'warning', 'critical', name='alert_severity')


def upgrade():
    # The alert_severity type is created implicitly by create_table below (it is
    # used by exactly this one column). An explicit .create() here would clash
    # with that implicit CREATE TYPE on Postgres.
    op.create_table(
        'telegram_accounts',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('org_id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=True),
        sa.Column('token', sa.String(length=48), nullable=False),
        sa.Column('chat_id', sa.String(length=40), nullable=True),
        sa.Column('label', sa.String(length=120), nullable=True),
        sa.Column(
            'muted_kinds',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column('min_severity', alert_severity, nullable=False, server_default='warning'),
        sa.Column('quiet_from_hour', sa.Integer(), nullable=True),
        sa.Column('quiet_to_hour', sa.Integer(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('activated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], ondelete='CASCADE'),
        # SET NULL, not CASCADE: deleting a panel login must not silently take
        # the director's alert chat with it.
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('token', name='uq_telegram_accounts_token'),
    )
    op.create_index('ix_telegram_accounts_org', 'telegram_accounts', ['org_id'])
    op.create_index('ix_telegram_accounts_chat', 'telegram_accounts', ['chat_id'])

    op.create_table(
        'notification_log',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('org_id', sa.UUID(), nullable=False),
        sa.Column('dedupe_key', sa.String(length=200), nullable=False),
        sa.Column('kind', sa.String(length=32), nullable=False),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('org_id', 'dedupe_key', name='uq_notification_log_org_key'),
    )
    op.create_index('ix_notification_log_sent_at', 'notification_log', ['sent_at'])


def downgrade():
    bind = op.get_bind()
    op.drop_index('ix_notification_log_sent_at', table_name='notification_log')
    op.drop_table('notification_log')
    op.drop_index('ix_telegram_accounts_chat', table_name='telegram_accounts')
    op.drop_index('ix_telegram_accounts_org', table_name='telegram_accounts')
    op.drop_table('telegram_accounts')
    alert_severity.drop(bind, checkfirst=True)
