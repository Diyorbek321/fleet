"""Which way a trip runs: UZ→RU or RU→UZ.

The customs post on the order sheet is in the country the load is going to,
and nothing on the trip said which that was. Nullable, and a plain string: the
trips already on file have no direction, and two values do not earn a
Postgres enum type that every later value would need a migration to extend.

Revision ID: e7f8a9b0c1d2
Revises: d6e7f8a9b0c1
"""
from alembic import op
import sqlalchemy as sa

revision = "e7f8a9b0c1d2"
down_revision = "d6e7f8a9b0c1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("trips", sa.Column("direction", sa.String(8), nullable=True))


def downgrade() -> None:
    op.drop_column("trips", "direction")
