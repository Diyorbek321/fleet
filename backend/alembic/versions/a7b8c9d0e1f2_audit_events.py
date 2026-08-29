"""Audit trail for platform-operator actions.

Everything a superadmin does is invisible from inside the tenant it happens to.
A company sees its account suspended, or a user it did not create, or — when
its data is only read — nothing at all. Without this table there is no answer
to "who did that, and when", neither for the customer asking nor for us.

Append-only by intent: nothing in the application updates or deletes a row, so
the record cannot be tidied afterwards by the person it describes.

``target_org_id`` is deliberately not a foreign key. The row has to outlive the
organization, and an organization deletion is the single event most worth
keeping.

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-08-29
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = 'a7b8c9d0e1f2'
down_revision = 'f6a7b8c9d0e1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'audit_events',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        # SET NULL, not CASCADE: removing a staff account must not erase the
        # record of what that account did.
        sa.Column(
            'actor_user_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('users.id', ondelete='SET NULL'),
            nullable=True,
        ),
        sa.Column('actor_email', sa.String(255), nullable=False),
        sa.Column('action', sa.String(64), nullable=False),
        sa.Column('target_org_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('target_org_name', sa.String(200), nullable=True),
        sa.Column('detail', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_audit_events_action', 'audit_events', ['action'])
    op.create_index('ix_audit_events_created_at', 'audit_events', ['created_at'])
    op.create_index('ix_audit_events_target_org', 'audit_events', ['target_org_id', 'created_at'])


def downgrade() -> None:
    op.drop_index('ix_audit_events_target_org', table_name='audit_events')
    op.drop_index('ix_audit_events_created_at', table_name='audit_events')
    op.drop_index('ix_audit_events_action', table_name='audit_events')
    op.drop_table('audit_events')
