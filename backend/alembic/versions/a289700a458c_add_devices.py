"""add devices

Revision ID: a289700a458c
Revises: b0eaec297dfc
Create Date: 2026-04-24 01:01:33.897175

"""
from alembic import op
import sqlalchemy as sa


revision = 'a289700a458c'
down_revision = 'b0eaec297dfc'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'devices',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('imei', sa.String(length=32), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=True),
        sa.Column('api_key_hash', sa.String(length=255), nullable=False),
        sa.Column('truck_id', sa.UUID(), nullable=True),
        sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['truck_id'], ['trucks.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_devices_imei'), 'devices', ['imei'], unique=True)


def downgrade():
    op.drop_index(op.f('ix_devices_imei'), table_name='devices')
    op.drop_table('devices')
