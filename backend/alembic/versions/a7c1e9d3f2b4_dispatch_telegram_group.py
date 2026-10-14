"""The dispatchers' Telegram group, for the morning fleet board.

``dispatch_telegram_groups`` binds one group per organization the way
``truck_telegram_groups`` binds a truck's: a one-time token in a ``startgroup``
link. ``board_sent_on`` is the Tashkent day the board last went there, which
keeps a fifteen-minute scheduler at one copy per morning.

Revision ID: a7c1e9d3f2b4
Revises: 3f9c2b7e4a1d
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "a7c1e9d3f2b4"
down_revision = "3f9c2b7e4a1d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dispatch_telegram_groups",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token", sa.String(48), nullable=False),
        sa.Column("chat_id", sa.String(40), nullable=True),
        sa.Column("chat_title", sa.String(200), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("board_sent_on", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("org_id", name="uq_dispatch_telegram_groups_org"),
        sa.UniqueConstraint("token", name="uq_dispatch_telegram_groups_token"),
    )
    op.create_index("ix_dispatch_telegram_groups_chat", "dispatch_telegram_groups", ["chat_id"])


def downgrade() -> None:
    op.drop_index("ix_dispatch_telegram_groups_chat", table_name="dispatch_telegram_groups")
    op.drop_table("dispatch_telegram_groups")
