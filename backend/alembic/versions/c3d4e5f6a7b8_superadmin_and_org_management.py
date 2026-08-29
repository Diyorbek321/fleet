"""superadmin role + organization management columns

Two changes that together turn ``organizations`` from a bare tenancy marker into
something the platform operator can actually administer:

1. A new ``superadmin`` value on the ``user_role`` enum. This is the platform
   operator's role — it does NOT widen tenant scoping (``get_org_id`` still
   returns the caller's own org); it only unlocks ``/api/organizations/*``.
2. Suspension + CRM columns on ``organizations``: ``is_active`` (false =
   suspended, logins rejected), ``contact_name`` / ``contact_phone`` (who to
   call at the customer), ``notes`` (internal free-form notes) and
   ``updated_at``.

All new columns carry a server_default so existing rows backfill in place: every
already-provisioned organization stays active and gets ``updated_at = now()``.
The server_defaults on ``is_active``/``updated_at`` match the model and are kept
permanently; the defaults on the nullable columns are unnecessary and none are
added there.

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-07-31 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'c3d4e5f6a7b8'
down_revision = 'b2c3d4e5f6a7'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()

    # 1. Extend the user_role enum (Postgres only; SQLite stores enums as VARCHAR
    # and needs no DDL). ``ALTER TYPE ... ADD VALUE`` historically could not run
    # inside a transaction block, which matters because Alembic wraps each
    # migration in one. Postgres 12+ (we target 16) lifted that restriction with
    # one caveat: the newly added label cannot be *used* in the same transaction.
    # We only add the label here and never insert a superadmin row in this
    # migration, so a plain op.execute is safe — no autocommit block needed.
    #
    # ``BEFORE 'admin'`` keeps the physical sort order of the type aligned with
    # the declaration order in app.models.enums.UserRole (superadmin first), so
    # ``ORDER BY role`` reads most-privileged-first. IF NOT EXISTS makes the
    # statement idempotent for environments that were patched by hand.
    if bind.dialect.name == 'postgresql':
        op.execute("ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'superadmin' BEFORE 'admin'")

    # 2. Organization management columns. batch_alter_table so SQLite-backed
    # environments rebuild the table instead of failing on ALTER; on Postgres
    # these emit plain ALTER TABLE statements.
    with op.batch_alter_table('organizations', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true())
        )
        batch_op.add_column(sa.Column('contact_name', sa.String(length=200), nullable=True))
        batch_op.add_column(sa.Column('contact_phone', sa.String(length=40), nullable=True))
        batch_op.add_column(sa.Column('notes', sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column(
                'updated_at',
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            )
        )


def downgrade():
    """Reverses the column additions only — the enum value is NOT removed.

    Postgres has no ``ALTER TYPE ... DROP VALUE``. The only way to remove
    'superadmin' from ``user_role`` would be to create a replacement type,
    rewrite every dependent column, and drop the old one — which fails outright
    if any row still uses the label, and rewrites the whole ``users`` table if
    not. That is far more destructive than the thing being undone, so we leave
    the label in place, exactly as the earlier 'driver' addition
    (c1d2e3f4a5b6) did. A leftover unused enum label is harmless: nothing
    validates against it and app.models.enums stops emitting it.

    Practical consequence: after downgrading, delete or re-role any remaining
    superadmin users yourself — they would otherwise keep a role the application
    code no longer understands.
    """
    with op.batch_alter_table('organizations', schema=None) as batch_op:
        batch_op.drop_column('updated_at')
        batch_op.drop_column('notes')
        batch_op.drop_column('contact_phone')
        batch_op.drop_column('contact_name')
        batch_op.drop_column('is_active')
