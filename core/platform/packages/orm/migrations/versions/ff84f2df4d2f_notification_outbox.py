"""notification_outbox

Revision ID: ff84f2df4d2f
Revises: 699ca3b82d04
Create Date: 2026-08-05 15:00:07.154293

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "ff84f2df4d2f"
down_revision: str | Sequence[str] | None = "699ca3b82d04"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "notification_templates",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("event_type", sa.String(length=255), nullable=False),
        sa.Column("channel", sa.String(length=50), nullable=False),
        sa.Column("subject_template", sa.Text(), nullable=True),
        sa.Column("body_template", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["ucp.tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema="ucp",
    )
    op.create_table(
        "notification_outbox",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_reason", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("owner_token", sa.String(length=128), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
        schema="ucp",
    )
    op.create_index(
        "ix_notif_outbox_pending",
        "notification_outbox",
        ["status", "created_at"],
        unique=False,
        schema="ucp",
        postgresql_where=sa.text("status = 'PENDING'"),
    )
    op.create_unique_constraint(
        "notification_template_idx",
        "notification_templates",
        ["tenant_id", "event_type", "channel"],
        schema="ucp",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        "notification_template_idx", "notification_templates", schema="ucp", type_="unique"
    )
    op.drop_index(
        "ix_notif_outbox_pending",
        table_name="notification_outbox",
        schema="ucp",
        postgresql_where=sa.text("status = 'PENDING'"),
    )
    op.drop_table("notification_outbox", schema="ucp")
    op.drop_table("notification_templates", schema="ucp")
