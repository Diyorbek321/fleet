"""Document expiries beside the insurance, and whether a trip runs loaded.

The insurance page grows into a documents page: a rig is stopped at a border
for a lapsed inspection or tachograph as surely as for a lapsed policy, and a
driver for a lapsed passport or chip card. Each document is one expiry date,
like the policies, because "when does it run out" is the only question the
desk asks of it. The driver's licence already had ``license_expiry``.

``trips.is_loaded`` is the dispatcher's mark for an empty leg (порожний рейс).
Every trip on file was booked as a freight order, so they are all loaded.

Revision ID: 3f9c2b7e4a1d
Revises: d1e2f3a4b5c6
"""
from alembic import op
import sqlalchemy as sa

revision = "3f9c2b7e4a1d"
down_revision = "d1e2f3a4b5c6"
branch_labels = None
depends_on = None

TRUCK_COLUMNS = (
    "inspection_expiry",
    "permit_expiry",
    "transport_license_expiry",
    "certificate_expiry",
    "tachograph_expiry",
)
DRIVER_COLUMNS = (
    "foreign_passport_expiry",
    "passport_expiry",
    "certificate_expiry",
    "chip_card_expiry",
)


def upgrade() -> None:
    for name in TRUCK_COLUMNS:
        op.add_column("trucks", sa.Column(name, sa.Date(), nullable=True))
    for name in DRIVER_COLUMNS:
        op.add_column("drivers", sa.Column(name, sa.Date(), nullable=True))
    op.add_column(
        "trips",
        sa.Column("is_loaded", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    op.drop_column("trips", "is_loaded")
    for name in reversed(DRIVER_COLUMNS):
        op.drop_column("drivers", name)
    for name in reversed(TRUCK_COLUMNS):
        op.drop_column("trucks", name)
