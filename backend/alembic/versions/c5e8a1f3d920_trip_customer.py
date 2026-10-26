"""The customer who ordered a trip ("заказчик").

Not the shipper or the consignee: the forwarder or trading house that books
the truck is often neither, and it is the name the desk sorts its board by.

Revision ID: c5e8a1f3d920
Revises: 9e4d1c7b2a60
"""
import sqlalchemy as sa
from alembic import op

revision = "c5e8a1f3d920"
down_revision = "9e4d1c7b2a60"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("trips", sa.Column("customer", sa.String(length=200), nullable=True))


def downgrade() -> None:
    op.drop_column("trips", "customer")
