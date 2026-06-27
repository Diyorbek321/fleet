"""trip_documents: driver-uploaded document photos, strictly per-trip

Creates the ``trip_documents`` table. Each row links a stored photo to exactly
one trip (``trip_id``) and its owning organization (``org_id``); the file itself
lives in object storage (DigitalOcean Spaces) and only the storage key is kept
here. Reads are served via short-lived presigned URLs.

Revision ID: d8e9f0a1b2c3
Revises: c7d8e9f0a1b2
Create Date: 2026-06-26 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'd8e9f0a1b2c3'
down_revision = 'c7d8e9f0a1b2'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'trip_documents',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('org_id', sa.UUID(), nullable=False),
        sa.Column('trip_id', sa.UUID(), nullable=False),
        sa.Column('driver_id', sa.UUID(), nullable=True),
        sa.Column('storage_key', sa.String(length=500), nullable=False),
        sa.Column('content_type', sa.String(length=120), nullable=True),
        sa.Column('size_bytes', sa.Integer(), nullable=True),
        sa.Column('category', sa.String(length=40), nullable=True),
        sa.Column('caption', sa.Text(), nullable=True),
        sa.Column('uploaded_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['trip_id'], ['trips.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['driver_id'], ['drivers.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_trip_documents_org_id', 'trip_documents', ['org_id'])
    op.create_index('ix_trip_documents_trip_id', 'trip_documents', ['trip_id'])
    op.create_index('ix_trip_documents_trip', 'trip_documents', ['trip_id', 'uploaded_at'])


def downgrade():
    op.drop_index('ix_trip_documents_trip', table_name='trip_documents')
    op.drop_index('ix_trip_documents_trip_id', table_name='trip_documents')
    op.drop_index('ix_trip_documents_org_id', table_name='trip_documents')
    op.drop_table('trip_documents')
