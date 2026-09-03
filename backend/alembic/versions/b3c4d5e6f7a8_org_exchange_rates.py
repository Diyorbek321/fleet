"""organizations: per-org USD exchange rates for cross-border expense reports

A trip's expenses are recorded in the currency they were paid in — tenge in
Kazakhstan, roubles in Russia, so'm at home — so the three columns cannot be
added together as they stand. These give an organization one rate per currency
to fall back on when a trip did not record its own exchange.

Nullable with no default on purpose: an unset rate means the report shows
native amounts and says the USD column is unavailable, which is honest. A
hardcoded default would quietly convert every past trip at a rate nobody chose
and go stale without anyone noticing.

Revision ID: b3c4d5e6f7a8
Revises: a7b8c9d0e1f2
Create Date: 2026-09-03 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'b3c4d5e6f7a8'
down_revision = 'a7b8c9d0e1f2'
branch_labels = None
depends_on = None

_COLUMNS = ('usd_to_kzt', 'usd_to_rub', 'usd_to_uzs')


def upgrade():
    for name in _COLUMNS:
        op.add_column('organizations', sa.Column(name, sa.Numeric(14, 4), nullable=True))


def downgrade():
    for name in reversed(_COLUMNS):
        op.drop_column('organizations', name)
