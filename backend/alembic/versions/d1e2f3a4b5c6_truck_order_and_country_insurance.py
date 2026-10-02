"""The dispatcher's own truck order, a policy per country, and longer plates.

``trucks.sort_order`` is the position the dispatcher dragged a truck to. NULL
until they first reorder, and NULL sorts after every placed truck, so a new
truck lands at the bottom of a hand-made list instead of jumping into it.

A rig crossing into Kazakhstan and Russia carries a separate policy for each,
each with its own expiry. ``insurance_expiry`` stays as the Uzbek one — every
date already entered there is the home policy — and the other two sit beside it.

Plates go from 20 to 40 characters: a rig is booked as "tractor / trailer",
and two plates with a separator do not fit in 20. The two places that copy the
plate (border-queue watches, trip expense reports) widen with it, or a long
plate saved on the truck would fail the moment it was copied.

Revision ID: d1e2f3a4b5c6
Revises: c3d4e5f6a7b9
"""
from alembic import op
import sqlalchemy as sa

revision = "d1e2f3a4b5c6"
down_revision = "c3d4e5f6a7b9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("trucks", sa.Column("sort_order", sa.Integer(), nullable=True))
    op.add_column("trucks", sa.Column("insurance_expiry_kz", sa.Date(), nullable=True))
    op.add_column("trucks", sa.Column("insurance_expiry_rf", sa.Date(), nullable=True))
    op.alter_column("trucks", "plate_number", type_=sa.String(40), existing_type=sa.String(20), existing_nullable=False)
    op.alter_column("queue_watches", "plate", type_=sa.String(40), existing_type=sa.String(20), existing_nullable=False)
    op.alter_column(
        "trip_expense_reports", "plate_number", type_=sa.String(40), existing_type=sa.String(20), existing_nullable=True
    )


def downgrade() -> None:
    op.alter_column(
        "trip_expense_reports", "plate_number", type_=sa.String(20), existing_type=sa.String(40), existing_nullable=True
    )
    op.alter_column("queue_watches", "plate", type_=sa.String(20), existing_type=sa.String(40), existing_nullable=False)
    op.alter_column("trucks", "plate_number", type_=sa.String(20), existing_type=sa.String(40), existing_nullable=False)
    op.drop_column("trucks", "insurance_expiry_rf")
    op.drop_column("trucks", "insurance_expiry_kz")
    op.drop_column("trucks", "sort_order")
