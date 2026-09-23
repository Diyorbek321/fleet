"""What a dispatcher actually types about a rig and about a driver.

Three shapes change together because they are one form's worth of work:

* a rig is two vehicles, so the tractor's make and the semi-trailer's make get
  a column each instead of sharing the free-text ``model``;
* the trailer's capacity class (standard / mega) is what a load is booked
  against, so it is an enum rather than a number nobody would fill in;
* a driver is reached on up to three numbers (cab SIM, personal, a RU/KZ SIM
  for the far leg) and is either ADR-cleared or not.

Everything added here is nullable or defaulted, and nothing existing is
dropped: ``drivers.email`` and ``drivers.license_expiry`` lose their inputs in
the panel but keep their data, because deleting a column is not reversible and
the fields were filled in for two years of drivers.

Revision ID: b1c2d3e4f5a6
Revises: a8b9c0d1e2f3
"""
from alembic import op
import sqlalchemy as sa

revision = "b1c2d3e4f5a6"
down_revision = "a8b9c0d1e2f3"
branch_labels = None
depends_on = None


TRAILER_VOLUME = "trailer_volume"
VOLUMES = ("standart", "mega")


def upgrade() -> None:
    bind = op.get_bind()
    volume = sa.Enum(*VOLUMES, name=TRAILER_VOLUME)
    volume.create(bind, checkfirst=True)

    # create_type=False: the type is created once above; letting add_column try
    # again is how this fails on a re-run.
    volume_col = sa.Enum(*VOLUMES, name=TRAILER_VOLUME, create_type=False)

    op.add_column("trucks", sa.Column("tractor_brand", sa.String(length=60), nullable=True))
    op.add_column("trucks", sa.Column("trailer_brand", sa.String(length=60), nullable=True))
    op.add_column("trucks", sa.Column("trailer_volume", volume_col, nullable=True))

    op.add_column("drivers", sa.Column("phone2", sa.String(length=20), nullable=True))
    op.add_column("drivers", sa.Column("phone3", sa.String(length=20), nullable=True))
    # server_default so the NOT NULL can be added to a populated table in one
    # pass; the column stays NOT NULL afterwards and the ORM supplies the value
    # on every insert from here on.
    op.add_column(
        "drivers",
        sa.Column("adr", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("drivers", "adr")
    op.drop_column("drivers", "phone3")
    op.drop_column("drivers", "phone2")

    op.drop_column("trucks", "trailer_volume")
    op.drop_column("trucks", "trailer_brand")
    op.drop_column("trucks", "tractor_brand")

    sa.Enum(name=TRAILER_VOLUME).drop(op.get_bind(), checkfirst=True)
