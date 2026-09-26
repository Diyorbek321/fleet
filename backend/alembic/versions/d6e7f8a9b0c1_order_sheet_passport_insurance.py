"""The fields a dispatcher's order sheet, driver card and truck card ask for.

Three changes, shipped together because the panel's forms change together:

* ``drivers.passport_number`` — the document dispatch actually copies onto the
  paperwork. ``license_number`` stops being required: the form no longer asks
  for it, but numbers already on file are kept.
* ``trucks.insurance_expiry`` — the date a policy runs out, so it can be seen
  before a rig is sent over a border without cover.
* ``trips`` — the lines of the order sheet sent to a driver that had nowhere to
  live: the border crossing, the loading and unloading addresses, the customs
  post, and the two contacts (at loading, and the declarant at customs).

Revision ID: d6e7f8a9b0c1
Revises: c5d6e7f8a9b0
"""
from alembic import op
import sqlalchemy as sa

revision = "d6e7f8a9b0c1"
down_revision = "c5d6e7f8a9b0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("drivers", sa.Column("passport_number", sa.String(20), nullable=True))
    op.alter_column("drivers", "license_number", existing_type=sa.String(50), nullable=True)

    op.add_column("trucks", sa.Column("insurance_expiry", sa.Date(), nullable=True))

    op.add_column("trips", sa.Column("border_crossing", sa.String(120), nullable=True))
    op.add_column("trips", sa.Column("loading_address", sa.Text(), nullable=True))
    op.add_column("trips", sa.Column("loading_contact", sa.String(200), nullable=True))
    op.add_column("trips", sa.Column("customs_point", sa.String(200), nullable=True))
    op.add_column("trips", sa.Column("unloading_address", sa.Text(), nullable=True))
    op.add_column("trips", sa.Column("declarant_contact", sa.String(200), nullable=True))


def downgrade() -> None:
    for col in (
        "declarant_contact",
        "unloading_address",
        "customs_point",
        "loading_contact",
        "loading_address",
        "border_crossing",
    ):
        op.drop_column("trips", col)
    op.drop_column("trucks", "insurance_expiry")
    # Rows created without a licence cannot go back under NOT NULL as-is.
    op.execute("UPDATE drivers SET license_number = 'N/A-' || id::text WHERE license_number IS NULL")
    op.alter_column("drivers", "license_number", existing_type=sa.String(50), nullable=False)
    op.drop_column("drivers", "passport_number")
