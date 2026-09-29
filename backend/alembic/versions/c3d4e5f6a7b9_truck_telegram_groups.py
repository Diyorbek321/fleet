"""A Telegram group per truck, and the order sheet posted there on a new trip.

Dispatchers already run one Telegram group per lorry — the driver, the
dispatcher, sometimes the owner — and paste every new order ("заявка") into
it by hand. ``truck_telegram_groups`` binds a group to a truck the same way an
owner chat is bound: a one-time token in a ``startgroup`` deep link, so the
panel never sees or accepts a chat id. One row per truck; relinking replaces it.

``trips.order_sent_at`` makes the post happen once per trip, whether the truck
was chosen at creation or on a later edit.

``organizations.trip_order_rules`` / ``trip_order_footer`` are the two parts of
the order sheet that belong to the company rather than the trip: the
"ОБЯЗАТЕЛЬНО К ИСПОЛНЕНИЮ" list and the dispatchers' phone numbers. NULL
rules means the built-in list.

Revision ID: c3d4e5f6a7b9
Revises: b2c3d4e5f6a8
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "c3d4e5f6a7b9"
down_revision = "b2c3d4e5f6a8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "truck_telegram_groups",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "truck_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("trucks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token", sa.String(48), nullable=False),
        sa.Column("chat_id", sa.String(40), nullable=True),
        sa.Column("chat_title", sa.String(200), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("truck_id", name="uq_truck_telegram_groups_truck"),
        sa.UniqueConstraint("token", name="uq_truck_telegram_groups_token"),
    )
    op.create_index("ix_truck_telegram_groups_chat", "truck_telegram_groups", ["chat_id"])
    op.add_column("trips", sa.Column("order_sent_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("organizations", sa.Column("trip_order_rules", sa.Text(), nullable=True))
    op.add_column("organizations", sa.Column("trip_order_footer", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("organizations", "trip_order_footer")
    op.drop_column("organizations", "trip_order_rules")
    op.drop_column("trips", "order_sent_at")
    op.drop_index("ix_truck_telegram_groups_chat", table_name="truck_telegram_groups")
    op.drop_table("truck_telegram_groups")
