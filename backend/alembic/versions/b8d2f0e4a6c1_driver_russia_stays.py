"""A driver's stays in Russia, for the 90-in-180-day count.

``driver_russia_stays`` holds one row per stay — entry date, exit date (NULL
while inside). A partial unique index keeps it to one open stay per driver.

Revision ID: b8d2f0e4a6c1
Revises: a7c1e9d3f2b4
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "b8d2f0e4a6c1"
down_revision = "a7c1e9d3f2b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "driver_russia_stays",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "driver_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("drivers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("entered_on", sa.Date(), nullable=False),
        sa.Column("left_on", sa.Date(), nullable=True),
        sa.Column("source", sa.String(10), nullable=False),
        sa.Column(
            "trip_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("trips.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("note", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_driver_russia_stays_driver", "driver_russia_stays", ["driver_id", "entered_on"])
    op.create_index(
        "uq_driver_russia_stays_open",
        "driver_russia_stays",
        ["driver_id"],
        unique=True,
        postgresql_where=sa.text("left_on IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_driver_russia_stays_open", table_name="driver_russia_stays")
    op.drop_index("ix_driver_russia_stays_driver", table_name="driver_russia_stays")
    op.drop_table("driver_russia_stays")
