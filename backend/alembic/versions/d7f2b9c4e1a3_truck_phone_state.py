"""What the driver's phone last said about itself.

Battery, whether it may track in the background, and the app version — so the
panel's "no signal" comes with a reason, and an outdated APK is visible.

Revision ID: d7f2b9c4e1a3
Revises: c5e8a1f3d920
"""
import sqlalchemy as sa
from alembic import op

revision = "d7f2b9c4e1a3"
down_revision = "c5e8a1f3d920"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("trucks", sa.Column("phone_battery", sa.Float(), nullable=True))
    op.add_column("trucks", sa.Column("phone_tracking", sa.String(length=16), nullable=True))
    op.add_column("trucks", sa.Column("phone_app_version", sa.String(length=20), nullable=True))
    op.add_column("trucks", sa.Column("phone_reported_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    for column in ("phone_reported_at", "phone_app_version", "phone_tracking", "phone_battery"):
        op.drop_column("trucks", column)
