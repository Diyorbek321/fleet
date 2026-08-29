"""Widen fuel_logs.cost_per_liter for so'm-denominated fuel prices

``NUMERIC(6, 2)`` caps a value at 9 999.99. That is fine for USD or EUR per
litre, but this product's customers are Uzbek fleets who record fuel in so'm,
where diesel runs around 12 000 UZS per litre — every realistic entry
overflowed and returned a 500.

It went unnoticed because the test suite ran on SQLite, which ignores NUMERIC
precision entirely, while production runs PostgreSQL, which enforces it. The
suite now migrates a real PostgreSQL database (see ``tests/conftest.py``), so
this class of divergence fails the tests instead of the customer.

``NUMERIC(12, 2)`` matches the other money columns in the schema
(``trip_reports.amount``, ``driver_expenses.amount``) and leaves room for
per-litre prices in any currency the fleets actually use. Widening precision is
a metadata-only change in PostgreSQL for existing rows — no rewrite, no data
loss, and it is safely reversible here because no stored value can exceed the
old bound.

Revision ID: b2c3d4e5f6a7
Revises: f0a1b2c3d4e5
"""
from alembic import op
import sqlalchemy as sa


revision = 'b2c3d4e5f6a7'
down_revision = 'f0a1b2c3d4e5'
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column(
        'fuel_logs',
        'cost_per_liter',
        existing_type=sa.Numeric(precision=6, scale=2),
        type_=sa.Numeric(precision=12, scale=2),
        existing_nullable=False,
    )


def downgrade():
    # Only safe while every stored price still fits in NUMERIC(6, 2); any row
    # written after the upgrade with a real so'm price will make this fail
    # loudly, which is the correct outcome — silently truncating a fuel price
    # would corrupt trip profitability figures.
    op.alter_column(
        'fuel_logs',
        'cost_per_liter',
        existing_type=sa.Numeric(precision=12, scale=2),
        type_=sa.Numeric(precision=6, scale=2),
        existing_nullable=False,
    )
