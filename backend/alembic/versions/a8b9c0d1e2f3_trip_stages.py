"""Driver checkpoints: the stage a load is at, and where.

``trip_status`` stays exactly as it was — every report, alert and margin is
built on it. This adds the finer checkpoint beside it, which is what the cargo
owner's message prints and what the arrival estimate learns from.

Both columns are nullable and nothing is backfilled: a trip that was running
before this deploy has no checkpoint history, and inventing one would poison
the medians the estimate is built on. Those trips simply show no stage until
their driver reports the next one.

Revision ID: a8b9c0d1e2f3
Revises: f7a8b9c0d1e2
"""
from alembic import op
import sqlalchemy as sa

revision = "a8b9c0d1e2f3"
down_revision = "f7a8b9c0d1e2"
branch_labels = None
depends_on = None


TRIP_STAGE = "trip_stage"
STAGE_PLACE = "stage_place"

STAGES = (
    "arrived_loading",
    "loaded_waiting_docs",
    "docs_received_en_route",
    "arrived_border",
    "crossed_border",
    "arrived_customs",
    "left_customs",
    "arrived_unloading",
    "unloaded",
)
PLACES = ("uz", "kz", "ru", "uz_kz", "kz_ru")


def upgrade() -> None:
    bind = op.get_bind()
    stage = sa.Enum(*STAGES, name=TRIP_STAGE)
    place = sa.Enum(*PLACES, name=STAGE_PLACE)
    stage.create(bind, checkfirst=True)
    place.create(bind, checkfirst=True)

    # create_type=False: the enums are created once above, and letting each
    # add_column try again is how this migration fails on the second table.
    stage_col = sa.Enum(*STAGES, name=TRIP_STAGE, create_type=False)
    place_col = sa.Enum(*PLACES, name=STAGE_PLACE, create_type=False)

    op.add_column("trips", sa.Column("current_stage", stage_col, nullable=True))
    op.add_column("trips", sa.Column("current_stage_place", place_col, nullable=True))
    op.add_column("trips", sa.Column("loaded_at", sa.DateTime(timezone=True), nullable=True))

    op.add_column("trip_events", sa.Column("stage", stage_col, nullable=True))
    op.add_column("trip_events", sa.Column("stage_place", place_col, nullable=True))

    # The arrival estimate asks one question of this table: "every stage row of
    # this org's trips, oldest first". Without this it seq-scans the timeline of
    # every trip the customer has ever run, on every message it sends.
    op.create_index(
        "ix_trip_events_stage_recorded",
        "trip_events",
        ["stage", "recorded_at"],
        postgresql_where=sa.text("stage IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_trip_events_stage_recorded", table_name="trip_events")
    op.drop_column("trip_events", "stage_place")
    op.drop_column("trip_events", "stage")
    op.drop_column("trips", "loaded_at")
    op.drop_column("trips", "current_stage_place")
    op.drop_column("trips", "current_stage")

    bind = op.get_bind()
    sa.Enum(name=STAGE_PLACE).drop(bind, checkfirst=True)
    sa.Enum(name=TRIP_STAGE).drop(bind, checkfirst=True)
