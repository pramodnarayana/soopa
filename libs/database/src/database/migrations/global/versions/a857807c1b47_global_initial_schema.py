"""global_initial_schema

Revision ID: a857807c1b47
Revises:
Create Date: 2026-06-25 09:43:15.682659

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a857807c1b47"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    # database_shards
    op.create_table(
        "database_shards",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("dsn", sa.String(length=1024), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )

    # users (case-insensitive email via functional index)
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("idp_user_id", sa.String(length=255), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idp_user_id"),
    )
    op.create_index(
        "uq_users_email_lower",
        "users",
        [sa.text("lower(email)")],
        unique=True,
    )

    # tenants
    op.create_table(
        "tenants",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("idp_tenant_id", sa.String(length=255), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("shard_id", sa.Integer(), nullable=False),
        sa.Column("tier", sa.String(length=50), nullable=False),
        sa.Column("shard_schema", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["shard_id"], ["database_shards.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idp_tenant_id"),
        sa.UniqueConstraint("name"),
        sa.UniqueConstraint("shard_schema"),
    )

    # tenant_users
    op.create_table(
        "tenant_users",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=50), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "user_id", name="uq_tenant_user"),
    )

    # trading_partners (global control plane copy)
    op.create_table(
        "trading_partners",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("partner_name", sa.String(length=255), nullable=False),
        sa.Column("as2_id", sa.String(length=255), nullable=True),
        sa.Column("direction", sa.String(length=50), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=True),
        sa.Column("public_cert_pem", sa.Text(), nullable=True),
        sa.Column("provision_status", sa.String(length=50), nullable=False),
        sa.Column("provisioned_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "tenant_id", name="uq_tp_tenant"),
    )

    # connections
    op.create_table(
        "connections",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("trading_partner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("connection_type", sa.String(length=50), nullable=False),
        sa.Column("host", sa.String(length=1024), nullable=True),
        sa.Column("port", sa.Integer(), nullable=True),
        sa.Column("direction", sa.String(length=50), nullable=False),
        sa.Column("credentials_vault_ref", sa.String(length=255), nullable=False),
        sa.Column("poll_interval_secs", sa.Integer(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["trading_partner_id", "tenant_id"],
            ["trading_partners.id", "trading_partners.tenant_id"],
            name="fk_connections_tp_tenant",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # routes
    op.create_table(
        "routes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("source_partner_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("target_partner_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_format", sa.String(length=50), nullable=False),
        sa.Column("target_format", sa.String(length=50), nullable=False),
        sa.Column("transaction_type", sa.String(length=50), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["source_partner_id", "tenant_id"],
            ["trading_partners.id", "trading_partners.tenant_id"],
            name="fk_routes_source_tp_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["target_partner_id", "tenant_id"],
            ["trading_partners.id", "trading_partners.tenant_id"],
            name="fk_routes_target_tp_tenant",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # field_mapping_rules
    op.create_table(
        "field_mapping_rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("route_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_path", sa.Text(), nullable=False),
        sa.Column("dest_path", sa.Text(), nullable=False),
        sa.Column("required", sa.Boolean(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["route_id"], ["routes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    # outbox
    op.create_table(
        "outbox",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index(
        "ix_global_outbox_pending",
        "outbox",
        ["status", "created_at"],
        unique=False,
        postgresql_where=sa.text("status = 'PENDING'"),
    )

    # system_audit_log
    op.create_table(
        "system_audit_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("trace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("event", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_system_audit_log_tenant_time",
        "system_audit_log",
        ["tenant_id", "created_at"],
        unique=False,
    )
    op.create_index("ix_system_audit_log_trace_id", "system_audit_log", ["trace_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_system_audit_log_trace_id", table_name="system_audit_log")
    op.drop_index("ix_system_audit_log_tenant_time", table_name="system_audit_log")
    op.drop_table("system_audit_log")
    op.drop_index("ix_global_outbox_pending", table_name="outbox")
    op.drop_table("outbox")
    op.drop_table("field_mapping_rules")
    op.drop_table("routes")
    op.drop_table("connections")
    op.drop_table("trading_partners")
    op.drop_table("tenant_users")
    op.drop_table("tenants")
    op.drop_index("uq_users_email_lower", table_name="users")
    op.drop_table("users")
    op.drop_table("database_shards")
