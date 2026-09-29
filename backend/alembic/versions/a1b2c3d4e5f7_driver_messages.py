"""Messages to a driver's phone, and a truck whose phone says its GPS is off.

``driver_messages`` is the driver's inbox: everything the dispatcher sent and
every automatic GPS warning. A push notification is gone once it is swiped
away, and a driver asked "did you see my message" needs somewhere to look. The
same row is the panel's record of what was sent and whether any device took it.

``dedupe_key`` is how the automatic warnings stay at "once": a watcher that
ticks every fifteen minutes inserts with the same key, and the unique
constraint turns every repeat into a no-op. Dispatcher messages carry no key —
Postgres lets any number of NULLs past a unique constraint.

``trucks.gps_disabled_at`` is set when the app reports location services
switched off, and cleared by the next fix or the app reporting them back on.

Revision ID: a1b2c3d4e5f7
Revises: e7f8a9b0c1d2
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "a1b2c3d4e5f7"
down_revision = "e7f8a9b0c1d2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "driver_messages",
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
        sa.Column(
            "truck_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("trucks.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "sent_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("dedupe_key", sa.String(200), nullable=True),
        sa.Column("devices_delivered", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("org_id", "dedupe_key", name="uq_driver_messages_org_key"),
    )
    op.create_index(
        "ix_driver_messages_driver_created", "driver_messages", ["driver_id", "created_at"]
    )
    op.add_column(
        "trucks", sa.Column("gps_disabled_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("trucks", "gps_disabled_at")
    op.drop_index("ix_driver_messages_driver_created", table_name="driver_messages")
    op.drop_table("driver_messages")
