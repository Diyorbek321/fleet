"""Plate numbers are unique within a fleet, not across the platform.

The global unique constraint on ``trucks.plate_number`` predates multi-tenancy
and outlived it. Two consequences, one of them a leak:

* A customer adding a plate another customer already had was told it exists.
  It does not exist in *their* fleet, and the error confirmed that some other
  company on the platform owns that truck.
* A truck sold from one fleet to another could not be added until the seller
  deleted their record — which they should not have to do, since their history
  for that truck is their own accounting.

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
"""
from alembic import op

revision = "e6f7a8b9c0d1"
down_revision = "d5e6f7a8b9c0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Named by Postgres when the column was declared unique=True.
    op.drop_constraint("trucks_plate_number_key", "trucks", type_="unique")
    op.create_unique_constraint(
        "uq_trucks_org_plate", "trucks", ["org_id", "plate_number"]
    )


def downgrade() -> None:
    # Only reversible while no two organizations share a plate; if one pair
    # does, this raises rather than silently dropping a truck.
    op.drop_constraint("uq_trucks_org_plate", "trucks", type_="unique")
    op.create_unique_constraint("trucks_plate_number_key", "trucks", ["plate_number"])
