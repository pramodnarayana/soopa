"""Initial Engine Core Data Plane schema for Integration Platform (tenant shards).

Revision ID: 0001_engine_core_schema
Revises:
Create Date: 2026-10-22 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from ip.engine.adapters.outbound.database.isolation import apply_tenant_isolation
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001_engine_core_schema"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ("engine",)
depends_on: str | Sequence[str] | None = None

_ENGINE_TABLES: tuple[str, ...] = (
    "inbound_records",
    "outbound_records",
    "replica_records",
    "replica_rejections",
    "normalized_records",
    "global_entity_map",
    "normalization_ledger",
    "normalization_rejections",
    "normalization_shadow_diffs",
    "pending_references",
    "ip_trace_events",
    "ip_outbox",
)


def upgrade() -> None:
    """Upgrade Engine Core Data Plane tables in tenant shard."""
    # 1. Layer 1: inbound_records
    op.create_table(
        "inbound_records",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("connection_id", sa.String(length=64), nullable=False),
        sa.Column("app_id", sa.String(length=64), server_default="", nullable=False),
        sa.Column("trace_id", sa.String(length=64), nullable=False),
        sa.Column("correlation_id", sa.String(length=255), nullable=True),
        sa.Column("parent_trace_id", sa.String(length=64), nullable=True),
        sa.Column("original_trace_id", sa.String(length=64), nullable=True),
        sa.Column("replay_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("stream_name", sa.String(length=128), nullable=False),
        sa.Column(
            "ingestion_mode",
            sa.String(length=32),
            server_default="PUSH_FULL",
            nullable=False,
        ),
        sa.Column("sync_run_id", sa.String(length=64), nullable=True),
        sa.Column("generation_id", sa.Integer(), nullable=True),
        sa.Column("external_event_id", sa.String(length=255), nullable=True),
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
    )
    op.create_index("idx_inbound_trace", "inbound_records", ["tenant_id", "trace_id"])
    op.create_index("idx_inbound_corr", "inbound_records", ["tenant_id", "correlation_id"])
    op.create_index("idx_inbound_conn", "inbound_records", ["tenant_id", "connection_id"])
    op.create_index("idx_inbound_app", "inbound_records", ["tenant_id", "app_id"])
    op.create_index(
        "uq_inbound_external_event",
        "inbound_records",
        ["tenant_id", "connection_id", "external_event_id"],
        unique=True,
        postgresql_where=sa.text("external_event_id IS NOT NULL"),
    )

    # 2. Layer 5: outbound_records
    op.create_table(
        "outbound_records",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("connection_id", sa.String(length=64), nullable=False),
        sa.Column("app_id", sa.String(length=64), nullable=False),
        sa.Column("trace_id", sa.String(length=64), nullable=False),
        sa.Column("correlation_id", sa.String(length=255), nullable=True),
        sa.Column("parent_trace_id", sa.String(length=64), nullable=True),
        sa.Column("original_trace_id", sa.String(length=64), nullable=True),
        sa.Column("replay_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("stream_name", sa.String(length=128), nullable=False),
        sa.Column("operation", sa.String(length=32), server_default="CREATE", nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        sa.Column("external_record_id", sa.String(length=255), nullable=True),
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
        sa.Column("failure_category", sa.String(length=64), nullable=True),
        sa.Column("retry_after_seconds", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", "sent_at"),
    )
    op.create_index("idx_outbound_trace", "outbound_records", ["tenant_id", "trace_id"])
    op.create_index("idx_outbound_corr", "outbound_records", ["tenant_id", "correlation_id"])
    op.create_index("idx_outbound_conn", "outbound_records", ["tenant_id", "connection_id"])
    op.create_index("idx_outbound_app", "outbound_records", ["tenant_id", "app_id"])
    op.create_index("idx_outbound_status", "outbound_records", ["tenant_id", "status"])
    op.create_index(
        "idx_outbound_idempotency",
        "outbound_records",
        ["tenant_id", "connection_id", "idempotency_key"],
    )

    # 3. Layer 2: replica_records & replica_rejections
    op.create_table(
        "replica_records",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("connection_id", sa.String(length=64), nullable=False),
        sa.Column("stream", sa.String(length=128), nullable=False),
        sa.Column("record_key", sa.String(length=64), nullable=False),
        sa.Column("primary_key_values", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("cursor_value", sa.String(length=255), nullable=True),
        sa.Column("cursor_kind", sa.String(length=32), nullable=True),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("data_hash", sa.String(length=64), nullable=False),
        sa.Column("version", sa.BigInteger(), server_default=sa.text("1"), nullable=False),
        sa.Column("generation_id", sa.BigInteger(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "last_seen_generation", sa.BigInteger(), server_default=sa.text("1"), nullable=False
        ),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("extracted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "source_inbound_record_id", sa.String(length=64), server_default="", nullable=False
        ),
        sa.Column("trace_id", sa.String(length=64), nullable=False),
        sa.Column("correlation_id", sa.String(length=255), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "connection_id",
            "stream",
            "record_key",
            name="uq_ip_replica_record_identity",
        ),
    )
    op.create_index("idx_replica_tenant_stream", "replica_records", ["tenant_id", "stream"])
    op.create_index("idx_replica_data_hash", "replica_records", ["tenant_id", "data_hash"])
    op.create_index("idx_replica_trace", "replica_records", ["tenant_id", "trace_id"])
    op.create_index("idx_replica_corr", "replica_records", ["tenant_id", "correlation_id"])
    op.create_index(
        "idx_replica_gen",
        "replica_records",
        ["tenant_id", "connection_id", "stream", "last_seen_generation"],
    )

    op.create_table(
        "replica_rejections",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("connection_id", sa.String(length=64), nullable=False),
        sa.Column("stream", sa.String(length=128), nullable=False),
        sa.Column("inbound_record_id", sa.String(length=64), nullable=False),
        sa.Column("record_index", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=64), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("trace_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_rejection_tenant_conn", "replica_rejections", ["tenant_id", "connection_id", "stream"]
    )
    op.create_index("idx_rejection_trace", "replica_rejections", ["tenant_id", "trace_id"])

    # 4. Layer 3: normalized_records & global_entity_map & ip_trace_events
    op.create_table(
        "normalized_records",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("connection_id", sa.String(length=64), nullable=False),
        sa.Column("canonical_type", sa.String(length=64), nullable=False),
        sa.Column("source_id", sa.String(length=255), nullable=False),
        sa.Column("canonical_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("trace_id", sa.String(length=64), nullable=False),
        sa.Column("correlation_id", sa.String(length=255), nullable=True),
        sa.Column("parent_trace_id", sa.String(length=64), nullable=True),
        sa.Column("original_trace_id", sa.String(length=64), nullable=True),
        sa.Column("replay_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("normalized_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_norm_tenant_type",
        "normalized_records",
        ["tenant_id", "canonical_type"],
    )
    op.create_index(
        "idx_norm_source_id",
        "normalized_records",
        ["tenant_id", "canonical_type", "source_id"],
    )
    op.create_index("idx_norm_trace", "normalized_records", ["tenant_id", "trace_id"])
    op.create_index("idx_norm_corr", "normalized_records", ["tenant_id", "correlation_id"])

    op.create_table(
        "global_entity_map",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("trace_id", sa.String(length=64), nullable=False),
        sa.Column("correlation_id", sa.String(length=255), nullable=True),
        sa.Column("parent_trace_id", sa.String(length=64), nullable=True),
        sa.Column("original_trace_id", sa.String(length=64), nullable=True),
        sa.Column("replay_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("entity_domain", sa.String(length=64), nullable=False),
        sa.Column("canonical_id", sa.String(length=64), nullable=False),
        sa.Column("source_connection_id", sa.String(length=64), nullable=False),
        sa.Column("source_entity_id", sa.String(length=255), nullable=False),
        sa.Column("dest_connection_id", sa.String(length=64), nullable=True),
        sa.Column("dest_entity_id", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "entity_domain",
            "source_connection_id",
            "source_entity_id",
            name="uq_ip_entity_map_source",
        ),
    )
    op.create_index(
        "idx_entity_map_canonical",
        "global_entity_map",
        ["tenant_id", "canonical_id"],
    )
    op.create_index(
        "idx_entity_map_trace",
        "global_entity_map",
        ["tenant_id", "trace_id"],
    )

    # 4. Layer 3: normalization_ledger
    op.create_table(
        "normalization_ledger",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("replica_record_id", sa.String(length=64), nullable=False),
        sa.Column("replica_version", sa.BigInteger(), nullable=False),
        sa.Column("mapping_id", sa.String(length=128), nullable=False),
        sa.Column("mapping_version", sa.Integer(), nullable=False),
        sa.Column(
            "produced_canonical_refs",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("trace_id", sa.String(length=64), nullable=False),
        sa.Column("correlation_id", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "replica_record_id",
            "mapping_id",
            "mapping_version",
            name="uq_ip_norm_ledger_replica_mapping",
        ),
    )
    op.create_index(
        "idx_norm_ledger_replica", "normalization_ledger", ["tenant_id", "replica_record_id"]
    )
    op.create_index("idx_norm_ledger_trace", "normalization_ledger", ["tenant_id", "trace_id"])

    # Layer 3: normalization_rejections
    op.create_table(
        "normalization_rejections",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("replica_record_id", sa.String(length=64), nullable=False),
        sa.Column("stream", sa.String(length=128), nullable=False),
        sa.Column("mapping_id", sa.String(length=128), nullable=False),
        sa.Column("mapping_version", sa.Integer(), nullable=False),
        sa.Column("reason_code", sa.String(length=64), nullable=False),
        sa.Column("field_path", sa.String(length=255), nullable=True),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("trace_id", sa.String(length=64), nullable=False),
        sa.Column("correlation_id", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_norm_rej_tenant_replica",
        "normalization_rejections",
        ["tenant_id", "replica_record_id"],
    )
    op.create_index("idx_norm_rej_trace", "normalization_rejections", ["tenant_id", "trace_id"])

    # Layer 3: normalization_shadow_diffs
    op.create_table(
        "normalization_shadow_diffs",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("replica_record_id", sa.String(length=64), nullable=False),
        sa.Column("candidate_version", sa.Integer(), nullable=False),
        sa.Column(
            "diff_data",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("trace_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_norm_diff_replica", "normalization_shadow_diffs", ["tenant_id", "replica_record_id"]
    )
    op.create_index("idx_norm_diff_trace", "normalization_shadow_diffs", ["tenant_id", "trace_id"])

    # Layer 3: pending_references
    op.create_table(
        "pending_references",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("source_connection_id", sa.String(length=64), nullable=False),
        sa.Column("target_canonical_type", sa.String(length=64), nullable=False),
        sa.Column("target_source_id", sa.String(length=255), nullable=False),
        sa.Column("referencing_canonical_type", sa.String(length=64), nullable=False),
        sa.Column("referencing_source_id", sa.String(length=255), nullable=False),
        sa.Column("referencing_field", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="PENDING", nullable=False),
        sa.Column("trace_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_pending_ref_target",
        "pending_references",
        ["tenant_id", "source_connection_id", "target_canonical_type", "target_source_id"],
    )
    op.create_index("idx_pending_ref_status", "pending_references", ["tenant_id", "status"])

    op.create_table(
        "ip_trace_events",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("trace_id", sa.String(length=64), nullable=False),
        sa.Column("correlation_id", sa.String(length=255), nullable=True),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("actor", sa.String(length=128), server_default="SYSTEM", nullable=False),
        sa.Column("metadata_", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", "created_at"),
    )
    op.create_index(
        "idx_ip_trace_events_trace",
        "ip_trace_events",
        ["tenant_id", "trace_id", "created_at"],
    )
    op.create_index(
        "idx_ip_trace_events_corr",
        "ip_trace_events",
        ["tenant_id", "correlation_id"],
    )
    op.create_index(
        "idx_ip_trace_events_type",
        "ip_trace_events",
        ["tenant_id", "event_type", "created_at"],
    )

    # 5. Data Plane Outbox: ip_outbox
    op.create_table(
        "ip_outbox",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
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
    )
    op.create_index(op.f("ix_ip_outbox_tenant_id"), "ip_outbox", ["tenant_id"])
    op.create_index(
        "ix_ip_dp_outbox_pending",
        "ip_outbox",
        ["status", "created_at"],
        postgresql_where=sa.text("status = 'PENDING'"),
    )

    # Enable Row-Level Security (RLS) across all tenant-scoped Engine Data Plane tables
    for table_name in _ENGINE_TABLES:
        apply_tenant_isolation(op, table_name)


def downgrade() -> None:
    """Downgrade Engine Core Data Plane tables in tenant shard."""
    for table_name in reversed(_ENGINE_TABLES):
        op.drop_table(table_name, if_exists=True)
