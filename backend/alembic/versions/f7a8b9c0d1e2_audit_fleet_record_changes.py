"""Audit rows can name a record, not just an organization.

The table was built for platform-operator actions, whose target is always a
whole customer. The figures an owner runs their business on are editable by
their own staff, and until now nothing recorded it: a trip could be deleted, its
rate rewritten, or the USD rate behind every cross-border expense report moved,
and the only evidence was that the number had changed.

Revision ID: f7a8b9c0d1e2
Revises: e6f7a8b9c0d1
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "f7a8b9c0d1e2"
down_revision = "e6f7a8b9c0d1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("audit_events", sa.Column("target_type", sa.String(32), nullable=True))
    op.add_column("audit_events", sa.Column("target_id", UUID(as_uuid=True), nullable=True))
    op.add_column("audit_events", sa.Column("target_label", sa.String(200), nullable=True))
    op.create_index(
        "ix_audit_events_target", "audit_events", ["target_type", "target_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_audit_events_target", table_name="audit_events")
    op.drop_column("audit_events", "target_label")
    op.drop_column("audit_events", "target_id")
    op.drop_column("audit_events", "target_type")
