"""multi-tenancy: organizations + org_id on tenant tables, GPS history index

Adds the ``organizations`` table and an ``org_id`` foreign key to every
tenant-owned table (users, trucks, drivers, devices, geofences, trips). Existing
rows in an already-deployed database are backfilled into a single "Default
Organization" so the NOT NULL constraint can be applied without data loss; after
deploying, move users/data into real organizations as needed.

Also adds the composite index on ``truck_location_history (truck_id, recorded_at)``
— the hot read path for history/report/analytics queries.

Revision ID: c7d8e9f0a1b2
Revises: b6c7d8e9f0a1
Create Date: 2026-06-25 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'c7d8e9f0a1b2'
down_revision = 'b6c7d8e9f0a1'
branch_labels = None
depends_on = None

# Stable id for the backfill organization so re-runs / multiple env deploys agree.
_DEFAULT_ORG_ID = '00000000-0000-0000-0000-000000000001'

_TENANT_TABLES = ('users', 'trucks', 'drivers', 'devices', 'geofences', 'trips')


def upgrade():
    op.create_table(
        'organizations',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )

    # Only create a backfill organization if there is pre-existing tenant data to
    # adopt. On a fresh database (new production deploy) we skip this so the app
    # starts with ZERO data — the first real org is created via /api/auth/register.
    conn = op.get_bind()
    existing_rows = conn.execute(
        sa.text(
            "SELECT "
            + " + ".join(f"(SELECT count(*) FROM {t})" for t in _TENANT_TABLES)
        )
    ).scalar() or 0
    need_backfill = existing_rows > 0

    if need_backfill:
        op.execute(
            sa.text(
                "INSERT INTO organizations (id, name, created_at) "
                "VALUES (CAST(:id AS uuid), 'Default Organization', now())"
            ).bindparams(id=_DEFAULT_ORG_ID)
        )

    for table in _TENANT_TABLES:
        op.add_column(table, sa.Column('org_id', sa.UUID(), nullable=True))
        if need_backfill:
            op.execute(
                sa.text(f"UPDATE {table} SET org_id = CAST(:id AS uuid) WHERE org_id IS NULL").bindparams(
                    id=_DEFAULT_ORG_ID
                )
            )
        op.alter_column(table, 'org_id', existing_type=sa.UUID(), nullable=False)
        op.create_index(f'ix_{table}_org_id', table, ['org_id'])
        op.create_foreign_key(
            f'fk_{table}_org_id', table, 'organizations', ['org_id'], ['id'], ondelete='CASCADE'
        )

    op.create_index(
        'ix_truck_location_history_truck_recorded',
        'truck_location_history',
        ['truck_id', 'recorded_at'],
    )


def downgrade():
    op.drop_index('ix_truck_location_history_truck_recorded', table_name='truck_location_history')
    for table in reversed(_TENANT_TABLES):
        op.drop_constraint(f'fk_{table}_org_id', table, type_='foreignkey')
        op.drop_index(f'ix_{table}_org_id', table_name=table)
        op.drop_column(table, 'org_id')
    op.drop_table('organizations')
