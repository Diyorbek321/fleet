"""The panel's bell: owner alerts, kept for the people who read the panel.

Every owner alert used to exist only as a Telegram message. A dispatcher who
never linked a chat — or whose chat was in its quiet hours — saw nothing at
all. ``panel_notifications`` keeps one row per alert fact, deduped on the same
key the Telegram bus uses, so the bell lists each fact once.

Read state is one timestamp per user rather than a row per user per alert:
the bell is "what happened since I last looked", and a join table would grow
with users × alerts for no question anyone asks.

Revision ID: b2c3d4e5f6a8
Revises: a1b2c3d4e5f7
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "b2c3d4e5f6a8"
down_revision = "a1b2c3d4e5f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "panel_notifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("path", sa.String(300), nullable=True),
        sa.Column("dedupe_key", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("org_id", "dedupe_key", name="uq_panel_notifications_org_key"),
    )
    op.create_index(
        "ix_panel_notifications_org_created", "panel_notifications", ["org_id", "created_at"]
    )
    op.add_column(
        "users", sa.Column("notifications_seen_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("users", "notifications_seen_at")
    op.drop_index("ix_panel_notifications_org_created", table_name="panel_notifications")
    op.drop_table("panel_notifications")
