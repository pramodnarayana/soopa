"""tenant_initial_schema

Revision ID: 534f8e33d17d
Revises:
Create Date: 2026-06-25 09:43:48.632423

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "534f8e33d17d"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # ── Replicated Config (synced from Global Control Plane) ──────────────────

    op.create_table(
        "trading_partners",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False, index=True),
        sa.Column("partner_name", sa.String(length=255), nullable=False),
        sa.Column("as2_id", sa.String(length=255), nullable=True),
        sa.Column("direction", sa.String(length=50), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=True),
        sa.Column("public_cert_pem", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_trading_partners_tenant_id"), "trading_partners", ["tenant_id"], unique=False
    )

    op.create_table(
        "connections",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False, index=True),
        sa.Column("trading_partner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("connection_type", sa.String(length=50), nullable=False),
        sa.Column("host", sa.String(length=1024), nullable=True),
        sa.Column("port", sa.Integer(), nullable=True),
        sa.Column("direction", sa.String(length=50), nullable=False),
        sa.Column("credentials_vault_ref", sa.String(length=255), nullable=False),
        sa.Column("poll_interval_secs", sa.Integer(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_connections_tenant_id"), "connections", ["tenant_id"], unique=False
    )

    op.create_table(
        "routes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False, index=True),
        sa.Column("source_partner_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("target_partner_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_format", sa.String(length=50), nullable=False),
        sa.Column("target_format", sa.String(length=50), nullable=False),
        sa.Column("transaction_type", sa.String(length=50), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_routes_tenant_id"), "routes", ["tenant_id"], unique=False)

    op.create_table(
        "field_mapping_rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False, index=True),
        sa.Column("route_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_path", sa.Text(), nullable=False),
        sa.Column("dest_path", sa.Text(), nullable=False),
        sa.Column("required", sa.Boolean(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_field_mapping_rules_tenant_id"),
        "field_mapping_rules",
        ["tenant_id"],
        unique=False,
    )

    # ── Domain Models ─────────────────────────────────────────────────────────

    op.create_table(
        "edi_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False, index=True),
        sa.Column("trace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("direction", sa.String(length=50), nullable=False),
        sa.Column("connection_type", sa.String(length=50), nullable=False),
        sa.Column("trading_partner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sender_id", sa.String(length=255), nullable=True),
        sa.Column("receiver_id", sa.String(length=255), nullable=True),
        sa.Column("as2_message_id", sa.String(length=255), nullable=True),
        sa.Column("interchange_control_no", sa.String(length=255), nullable=True),
        sa.Column("transaction_type", sa.String(length=50), nullable=True),
        sa.Column("format_standard", sa.String(length=50), nullable=True),
        sa.Column("s3_key", sa.String(length=1024), nullable=False),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_edi_messages_tenant_id"), "edi_messages", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_edi_messages_trace_id"), "edi_messages", ["trace_id"], unique=False)
    op.create_index(
        "ix_edi_msgs_partner_time", "edi_messages", ["trading_partner_id", "created_at"]
    )

    op.create_table(
        "api_payloads",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False, index=True),
        sa.Column("trace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("direction", sa.String(length=50), nullable=False),
        sa.Column("route_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("webhook_url", sa.String(length=1024), nullable=True),
        sa.Column("http_status_code", sa.Integer(), nullable=True),
        sa.Column("target_format", sa.String(length=50), nullable=True),
        sa.Column("s3_key", sa.String(length=1024), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_api_payloads_tenant_id"), "api_payloads", ["tenant_id"], unique=False
    )
    op.create_index(
        op.f("ix_api_payloads_trace_id"), "api_payloads", ["trace_id"], unique=False
    )

    op.create_table(
        "jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False, index=True),
        sa.Column("trace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("type", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_jobs_tenant_id"), "jobs", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_jobs_trace_id"), "jobs", ["trace_id"], unique=False)

    op.create_table(
        "outbox",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False, index=True),
        sa.Column("idempotency_key", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=True),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index(op.f("ix_outbox_tenant_id"), "outbox", ["tenant_id"], unique=False)
    op.create_index(
        "ix_tenant_outbox_pending",
        "outbox",
        ["status", "created_at"],
        unique=False,
        postgresql_where=sa.text("status = 'PENDING'"),
    )

    op.create_table(
        "processed_events",
        sa.Column("idempotency_key", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False, index=True),
        sa.Column("processed_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("idempotency_key"),
    )
    op.create_index(
        op.f("ix_processed_events_tenant_id"), "processed_events", ["tenant_id"], unique=False
    )

    op.create_table(
        "audit_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False, index=True),
        sa.Column("trace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("step", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_audit_log_tenant_id"), "audit_log", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_audit_log_trace_id"), "audit_log", ["trace_id"], unique=False)

    op.create_table(
        "ack_receipts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False, index=True),
        sa.Column("trace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("type", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("raw_content", sa.Text(), nullable=True),
        sa.Column("received_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_ack_receipts_tenant_id"), "ack_receipts", ["tenant_id"], unique=False
    )
    op.create_index(
        op.f("ix_ack_receipts_trace_id"), "ack_receipts", ["trace_id"], unique=False
    )

    # ── Row-Level Security ────────────────────────────────────────────────────
    rls_tables = [
        "trading_partners",
        "connections",
        "routes",
        "field_mapping_rules",
        "edi_messages",
        "api_payloads",
        "jobs",
        "outbox",
        "processed_events",
        "audit_log",
        "ack_receipts",
    ]
    for table in rls_tables:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
        op.execute(
            f"CREATE POLICY tenant_isolation_policy ON {table} "
            f"USING (tenant_id = current_setting('app.current_tenant')::integer);"
        )


def downgrade() -> None:
    """Downgrade schema."""
    rls_tables = [
        "ack_receipts",
        "audit_log",
        "processed_events",
        "outbox",
        "jobs",
        "api_payloads",
        "edi_messages",
        "field_mapping_rules",
        "routes",
        "connections",
        "trading_partners",
    ]
    for table in rls_tables:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation_policy ON {table};")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")

    op.drop_index(op.f("ix_ack_receipts_trace_id"), table_name="ack_receipts")
    op.drop_index(op.f("ix_ack_receipts_tenant_id"), table_name="ack_receipts")
    op.drop_table("ack_receipts")

    op.drop_index(op.f("ix_audit_log_trace_id"), table_name="audit_log")
    op.drop_index(op.f("ix_audit_log_tenant_id"), table_name="audit_log")
    op.drop_table("audit_log")

    op.drop_index(op.f("ix_processed_events_tenant_id"), table_name="processed_events")
    op.drop_table("processed_events")

    op.drop_index("ix_tenant_outbox_pending", table_name="outbox")
    op.drop_index(op.f("ix_outbox_tenant_id"), table_name="outbox")
    op.drop_table("outbox")

    op.drop_index(op.f("ix_jobs_trace_id"), table_name="jobs")
    op.drop_index(op.f("ix_jobs_tenant_id"), table_name="jobs")
    op.drop_table("jobs")

    op.drop_index(op.f("ix_api_payloads_trace_id"), table_name="api_payloads")
    op.drop_index(op.f("ix_api_payloads_tenant_id"), table_name="api_payloads")
    op.drop_table("api_payloads")

    op.drop_index("ix_edi_msgs_partner_time", table_name="edi_messages")
    op.drop_index(op.f("ix_edi_messages_trace_id"), table_name="edi_messages")
    op.drop_index(op.f("ix_edi_messages_tenant_id"), table_name="edi_messages")
    op.drop_table("edi_messages")

    op.drop_index(op.f("ix_field_mapping_rules_tenant_id"), table_name="field_mapping_rules")
    op.drop_table("field_mapping_rules")

    op.drop_index(op.f("ix_routes_tenant_id"), table_name="routes")
    op.drop_table("routes")

    op.drop_index(op.f("ix_connections_tenant_id"), table_name="connections")
    op.drop_table("connections")

    op.drop_index(op.f("ix_trading_partners_tenant_id"), table_name="trading_partners")
    op.drop_table("trading_partners")
