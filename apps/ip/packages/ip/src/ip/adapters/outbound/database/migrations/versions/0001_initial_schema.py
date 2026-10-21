"""Initial schema for Integration Platform (IP).

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-10-18 19:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001_initial_schema"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "connections",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("app_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("auth_type", sa.String(length=32), nullable=False),
        sa.Column("public_config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("encrypted_credentials", sa.LargeBinary(), nullable=True),
        sa.Column(
            "key_encryption_version",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column("connection_fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default="PENDING_AUTH",
            nullable=False,
        ),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_refreshed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=64), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        schema="ip",
    )
    op.create_index(
        "uq_tenant_active_fingerprint",
        "connections",
        ["tenant_id", "connection_fingerprint"],
        unique=True,
        schema="ip",
        postgresql_where=sa.text("status != 'DEACTIVATED'"),
    )
    op.create_index(
        op.f("ix_ip_connections_tenant_id"),
        "connections",
        ["tenant_id"],
        unique=False,
        schema="ip",
    )
    op.create_table(
        "connection_catalogs",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("connection_id", sa.String(length=64), nullable=False),
        sa.Column(
            "catalog_version",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column("catalog_hash", sa.String(length=64), nullable=False),
        sa.Column("schema_definition", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "connection_id", "catalog_version", name="uq_ip_catalog_connection_version"
        ),
        schema="ip",
    )
    op.create_index(
        op.f("ix_ip_connection_catalogs_connection_id"),
        "connection_catalogs",
        ["connection_id"],
        unique=False,
        schema="ip",
    )
    op.create_table(
        "outbox",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=50), server_default="PENDING", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_reason", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("owner_token", sa.String(length=128), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
        schema="ip",
    )
    op.create_index(
        op.f("ix_ip_outbox_tenant_id"),
        "outbox",
        ["tenant_id"],
        unique=False,
        schema="ip",
    )
    op.create_index(
        "ix_ip_outbox_pending",
        "outbox",
        ["status", "created_at"],
        unique=False,
        postgresql_where=sa.text("status = 'PENDING'"),
        schema="ip",
    )
    op.create_table(
        "inbound_records",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("connection_id", sa.String(length=64), nullable=False),
        sa.Column("app_id", sa.String(length=64), server_default="", nullable=False),
        sa.Column("business_trace_id", sa.String(length=64), nullable=False),
        sa.Column("business_correlation_id", sa.String(length=255), nullable=True),
        sa.Column("stream_name", sa.String(length=128), nullable=False),
        sa.Column(
            "request_headers",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("request_body", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("request_s3_key", sa.String(length=512), nullable=True),
        sa.Column("request_size_bytes", sa.Integer(), nullable=False),
        sa.Column("request_sha256", sa.String(length=64), nullable=False),
        sa.Column("response_status_code", sa.Integer(), nullable=True),
        sa.Column("response_headers", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("response_body", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("response_s3_key", sa.String(length=512), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", "received_at"),
        schema="ip",
    )
    op.create_index(
        "idx_inbound_trace",
        "inbound_records",
        ["tenant_id", "business_trace_id"],
        unique=False,
        schema="ip",
    )
    op.create_index(
        "idx_inbound_corr",
        "inbound_records",
        ["tenant_id", "business_correlation_id"],
        unique=False,
        schema="ip",
    )
    op.create_index(
        "idx_inbound_conn",
        "inbound_records",
        ["tenant_id", "connection_id"],
        unique=False,
        schema="ip",
    )
    op.create_index(
        "idx_inbound_app",
        "inbound_records",
        ["tenant_id", "app_id"],
        unique=False,
        schema="ip",
    )
    op.create_table(
        "outbound_records",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("connection_id", sa.String(length=64), nullable=False),
        sa.Column("app_id", sa.String(length=64), nullable=False),
        sa.Column("business_trace_id", sa.String(length=64), nullable=False),
        sa.Column("business_correlation_id", sa.String(length=255), nullable=True),
        sa.Column("stream_name", sa.String(length=128), nullable=False),
        sa.Column("target_url", sa.String(length=1024), nullable=False),
        sa.Column("http_method", sa.String(length=16), nullable=False),
        sa.Column(
            "request_headers",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("request_body", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("request_s3_key", sa.String(length=512), nullable=True),
        sa.Column("request_size_bytes", sa.Integer(), nullable=False),
        sa.Column("request_sha256", sa.String(length=64), nullable=False),
        sa.Column("response_status_code", sa.Integer(), nullable=True),
        sa.Column("response_headers", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("response_body", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("response_s3_key", sa.String(length=512), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("attempt_number", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="PENDING", nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", "sent_at"),
        schema="ip",
    )
    op.create_index(
        "idx_outbound_trace",
        "outbound_records",
        ["tenant_id", "business_trace_id"],
        unique=False,
        schema="ip",
    )
    op.create_index(
        "idx_outbound_corr",
        "outbound_records",
        ["tenant_id", "business_correlation_id"],
        unique=False,
        schema="ip",
    )
    op.create_index(
        "idx_outbound_conn",
        "outbound_records",
        ["tenant_id", "connection_id"],
        unique=False,
        schema="ip",
    )
    op.create_index(
        "idx_outbound_app",
        "outbound_records",
        ["tenant_id", "app_id"],
        unique=False,
        schema="ip",
    )
    op.create_index(
        "idx_outbound_status",
        "outbound_records",
        ["tenant_id", "status"],
        unique=False,
        schema="ip",
    )
    op.create_table(
        "connection_stream_states",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("connection_id", sa.String(length=64), nullable=False),
        sa.Column("stream_name", sa.String(length=128), nullable=False),
        sa.Column("cursor_field", sa.String(length=128), nullable=True),
        sa.Column("cursor_value", sa.Text(), nullable=True),
        sa.Column(
            "records_synced_count", sa.BigInteger(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["ip.connections.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "connection_id",
            "stream_name",
            name="uq_ip_stream_state_tenant_conn_stream",
        ),
        schema="ip",
    )
    op.create_index(
        "idx_ip_stream_state_conn",
        "connection_stream_states",
        ["tenant_id", "connection_id"],
        unique=False,
        schema="ip",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "idx_ip_stream_state_conn",
        table_name="connection_stream_states",
        schema="ip",
    )
    op.drop_table("connection_stream_states", schema="ip")
    op.drop_index(
        "idx_outbound_status",
        table_name="outbound_records",
        schema="ip",
    )
    op.drop_index(
        "idx_outbound_app",
        table_name="outbound_records",
        schema="ip",
    )
    op.drop_index(
        "idx_outbound_conn",
        table_name="outbound_records",
        schema="ip",
    )
    op.drop_index(
        "idx_outbound_corr",
        table_name="outbound_records",
        schema="ip",
    )
    op.drop_index(
        "idx_outbound_trace",
        table_name="outbound_records",
        schema="ip",
    )
    op.drop_table("outbound_records", schema="ip")
    op.drop_index(
        "idx_inbound_app",
        table_name="inbound_records",
        schema="ip",
    )
    op.drop_index(
        "idx_inbound_conn",
        table_name="inbound_records",
        schema="ip",
    )
    op.drop_index(
        "idx_inbound_corr",
        table_name="inbound_records",
        schema="ip",
    )
    op.drop_index(
        "idx_inbound_trace",
        table_name="inbound_records",
        schema="ip",
    )
    op.drop_table("inbound_records", schema="ip")
    op.drop_index(
        "ix_ip_outbox_pending",
        table_name="outbox",
        schema="ip",
    )
    op.drop_index(
        op.f("ix_ip_outbox_tenant_id"),
        table_name="outbox",
        schema="ip",
    )
    op.drop_table("outbox", schema="ip")
    op.drop_index(
        op.f("ix_ip_connection_catalogs_connection_id"),
        table_name="connection_catalogs",
        schema="ip",
    )
    op.drop_table("connection_catalogs", schema="ip")
    op.drop_index(
        op.f("ix_ip_connections_tenant_id"),
        table_name="connections",
        schema="ip",
    )
    op.drop_index(
        "uq_tenant_active_fingerprint",
        table_name="connections",
        schema="ip",
    )
    op.drop_table("connections", schema="ip")
