"""trip_expense_reports: digitized per-trip driver expense report ("yo'l varaqasi")

Creates ``trip_expense_reports`` (one per trip: header, money issued in
USD/RUB/KZT/UZS, currency-exchange rows, border-crossing timestamps, footer),
``trip_fuel_rows`` (numbered GSM rows split by KZ/RF/DOHA/E1CARD), and
``trip_country_expense_lines`` (one cell per country x category, e.g.
KZ + Платон = amount).

Revision ID: f0a1b2c3d4e5
Revises: e9f0a1b2c3d4
Create Date: 2026-07-11 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'f0a1b2c3d4e5'
down_revision = 'e9f0a1b2c3d4'
branch_labels = None
depends_on = None


trip_report_status = sa.Enum('draft', 'submitted', name='trip_report_status')
trip_report_country = sa.Enum('kz', 'ru', 'uz', name='trip_report_country')
trip_report_expense_category = sa.Enum(
    'platon', 'food', 'traffic_police', 'adblue', 'fine', 'spare_parts', 'repair',
    'refund', 'parking', 'phone', 'transport', 'shower', 'groceries',
    'parking_paperwork', 'taxi', 'carwash',
    name='trip_report_expense_category',
)


def upgrade():
    # Enums are created implicitly by the create_table calls below (each is
    # used by exactly one table); an explicit .create() here would clash with
    # that implicit CREATE TYPE on Postgres.
    op.create_table(
        'trip_expense_reports',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('org_id', sa.UUID(), nullable=False),
        sa.Column('trip_id', sa.UUID(), nullable=False),
        sa.Column('plate_number', sa.String(length=20), nullable=True),
        sa.Column('driver_name', sa.String(length=200), nullable=True),
        sa.Column('report_date', sa.Date(), nullable=True),
        sa.Column('odometer_out', sa.Numeric(12, 2), nullable=True),
        sa.Column('odometer_in', sa.Numeric(12, 2), nullable=True),
        sa.Column('fuel_at_garage', sa.Numeric(10, 2), nullable=True),
        sa.Column('route_text', sa.String(length=255), nullable=True),
        sa.Column('exchange_rate_note', sa.String(length=255), nullable=True),
        sa.Column('money_usd', sa.Numeric(12, 2), nullable=True),
        sa.Column('money_rub', sa.Numeric(12, 2), nullable=True),
        sa.Column('money_kzt', sa.Numeric(12, 2), nullable=True),
        sa.Column('money_uzs', sa.Numeric(14, 2), nullable=True),
        sa.Column('usd_to_kzt_given', sa.Numeric(12, 2), nullable=True),
        sa.Column('usd_to_kzt_received', sa.Numeric(12, 2), nullable=True),
        sa.Column('usd_to_rub_given', sa.Numeric(12, 2), nullable=True),
        sa.Column('usd_to_rub_received', sa.Numeric(12, 2), nullable=True),
        sa.Column('border_departure_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('border_arrival_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('electronic_pass_note', sa.String(length=255), nullable=True),
        sa.Column('electronic_queue_note', sa.String(length=255), nullable=True),
        sa.Column('insurance_rf', sa.Numeric(12, 2), nullable=True),
        sa.Column('insurance_kz', sa.Numeric(12, 2), nullable=True),
        sa.Column('dollar_return', sa.Numeric(12, 2), nullable=True),
        sa.Column('driver_comment', sa.Text(), nullable=True),
        sa.Column('status', trip_report_status, nullable=False, server_default='draft'),
        sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['trip_id'], ['trips.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_trip_expense_reports_org_id', 'trip_expense_reports', ['org_id'])
    op.create_index('ix_trip_expense_reports_trip', 'trip_expense_reports', ['trip_id'], unique=True)

    op.create_table(
        'trip_fuel_rows',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('report_id', sa.UUID(), nullable=False),
        sa.Column('row_no', sa.Integer(), nullable=False),
        sa.Column('kz_liters', sa.Numeric(8, 2), nullable=True),
        sa.Column('kz_amount', sa.Numeric(12, 2), nullable=True),
        sa.Column('rf_liters', sa.Numeric(8, 2), nullable=True),
        sa.Column('rf_amount', sa.Numeric(12, 2), nullable=True),
        sa.Column('doha_liters', sa.Numeric(8, 2), nullable=True),
        sa.Column('doha_amount', sa.Numeric(12, 2), nullable=True),
        sa.Column('e1card_liters', sa.Numeric(8, 2), nullable=True),
        sa.Column('e1card_amount', sa.Numeric(12, 2), nullable=True),
        sa.ForeignKeyConstraint(['report_id'], ['trip_expense_reports.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_trip_fuel_rows_report', 'trip_fuel_rows', ['report_id', 'row_no'])

    op.create_table(
        'trip_country_expense_lines',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('report_id', sa.UUID(), nullable=False),
        sa.Column('country', trip_report_country, nullable=False),
        sa.Column('category', trip_report_expense_category, nullable=False),
        sa.Column('amount', sa.Numeric(12, 2), nullable=False),
        sa.ForeignKeyConstraint(['report_id'], ['trip_expense_reports.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('report_id', 'country', 'category', name='uq_trip_country_expense_cell'),
    )


def downgrade():
    bind = op.get_bind()
    op.drop_table('trip_country_expense_lines')
    trip_report_expense_category.drop(bind, checkfirst=True)
    trip_report_country.drop(bind, checkfirst=True)

    op.drop_index('ix_trip_fuel_rows_report', table_name='trip_fuel_rows')
    op.drop_table('trip_fuel_rows')

    op.drop_index('ix_trip_expense_reports_trip', table_name='trip_expense_reports')
    op.drop_index('ix_trip_expense_reports_org_id', table_name='trip_expense_reports')
    op.drop_table('trip_expense_reports')
    trip_report_status.drop(bind, checkfirst=True)
