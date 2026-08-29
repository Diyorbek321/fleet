"""Password changes invalidate every existing session.

Resetting a password did nothing to the tokens already out there. The refresh
store is keyed by the token string, so there was no way to ask it for "every
token belonging to this user" — an admin who reset a compromised account's
password left the attacker's refresh token working for the full
``REFRESH_TOKEN_EXPIRE_DAYS`` (90 by default). The reset felt like a remedy and
was not one.

``users.password_changed_at`` is the fix: it goes into every token that is
minted, and any token stamped before the column's current value is rejected.
One column invalidates access and refresh tokens together, for every device,
with no per-token bookkeeping.

``must_change_password`` covers the other half. An admin-set password is a
password the admin knows; the flag marks the account so the client can force
the user to pick their own before doing anything else.

Backfill: existing rows get ``created_at``, not ``now()``. Using ``now()`` would
stamp every account as "changed this instant" and invalidate every live session
on the platform the moment this migration runs — logging out every driver
mid-shift for a change that is supposed to be invisible.

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-08-29
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = 'f6a7b8c9d0e1'
down_revision = 'e5f6a7b8c9d0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column('password_changed_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        'users',
        sa.Column(
            'must_change_password',
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    # See the module docstring: created_at, never now().
    op.execute('UPDATE users SET password_changed_at = created_at')
    op.alter_column('users', 'password_changed_at', nullable=False)


def downgrade() -> None:
    op.drop_column('users', 'must_change_password')
    op.drop_column('users', 'password_changed_at')
