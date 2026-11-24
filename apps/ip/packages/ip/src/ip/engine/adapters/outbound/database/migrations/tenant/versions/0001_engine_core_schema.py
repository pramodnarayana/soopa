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
    "quarantine_records",
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
    "ip_processed_events",
    "ip_batch_manifests",
    "ip_replay_ledger",
)

_ORCHESTRATION_TABLES_RLS: tuple[str, ...] = (
    "workflow_runs",
    "workflow_step_runs",
    "workflow_active_leases",
    "workflow_step_attempts",
    "workflow_payloads",
    "workflow_idempotency_keys",
    "workflow_matches",
    "workflow_match_conditions",
    "workflow_queue_items",
    "workflow_paused_queue_items",
    "workflow_concurrency_slots",
    "workflow_rate_limit_buckets",
)

_ORCHESTRATION_TABLES: tuple[str, ...] = (
    *_ORCHESTRATION_TABLES_RLS,
    "workflow_queue_cursors",
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
        sa.Column("batch_id", sa.String(length=64), server_default="", nullable=False),
        sa.Column("batch_seq", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("causation_depth", sa.Integer(), server_default=sa.text("0"), nullable=False),
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
    op.create_index(
        "idx_inbound_batch_range",
        "inbound_records",
        ["tenant_id", "batch_id", "batch_seq", "id"],
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
        sa.Column(
            "conflict_strategy",
            sa.String(length=32),
            server_default="FAIL",
            nullable=False,
        ),
        sa.Column("status", sa.String(length=32), server_default="PENDING", nullable=False),
        sa.Column("failure_category", sa.String(length=64), nullable=True),
        sa.Column("retry_after_seconds", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("causation_depth", sa.Integer(), server_default=sa.text("0"), nullable=False),
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

    op.create_table(
        "quarantine_records",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("connection_id", sa.String(length=64), nullable=False),
        sa.Column("outbound_record_id", sa.String(length=64), nullable=False),
        sa.Column("stream_name", sa.String(length=128), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        sa.Column("trace_id", sa.String(length=64), nullable=False),
        sa.Column("correlation_id", sa.String(length=255), nullable=True),
        sa.Column("failure_category", sa.String(length=64), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.Column("response_status_code", sa.Integer(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("request_body", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("request_s3_key", sa.String(length=512), nullable=True),
        sa.Column("response_body", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("response_s3_key", sa.String(length=512), nullable=True),
        sa.Column("quarantined_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_quarantine_tenant_time",
        "quarantine_records",
        ["tenant_id", "quarantined_at"],
    )
    op.create_index(
        "idx_quarantine_outbound",
        "quarantine_records",
        ["tenant_id", "outbound_record_id"],
    )
    op.create_index("idx_quarantine_trace", "quarantine_records", ["tenant_id", "trace_id"])

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
        sa.Column("source_inbound_record_id", sa.String(length=64), server_default="", nullable=False),
        sa.Column("trace_id", sa.String(length=128), nullable=False),
        sa.Column("correlation_id", sa.String(length=255), nullable=True),
        sa.Column("parent_trace_id", sa.String(length=128), nullable=True),
        sa.Column("original_trace_id", sa.String(length=128), nullable=True),
        sa.Column("replay_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
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
        sa.Column("trace_id", sa.String(length=128), nullable=False),
        sa.Column("correlation_id", sa.String(length=255), nullable=True),
        sa.Column("parent_trace_id", sa.String(length=128), nullable=True),
        sa.Column("original_trace_id", sa.String(length=128), nullable=True),
        sa.Column("replay_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_rejection_tenant_conn", "replica_rejections", ["tenant_id", "connection_id", "stream"]
    )
    op.create_index("idx_rejection_trace", "replica_rejections", ["tenant_id", "trace_id"])
    op.create_index("idx_rejection_corr", "replica_rejections", ["tenant_id", "correlation_id"])

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
        sa.Column("transformation_id", sa.String(length=128), nullable=False),
        sa.Column("transformation_version", sa.Integer(), nullable=False),
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
            "transformation_id",
            "transformation_version",
            name="uq_ip_norm_ledger_replica_transformation",
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
        sa.Column("transformation_id", sa.String(length=128), nullable=False),
        sa.Column("transformation_version", sa.Integer(), nullable=False),
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

    # 5. Data Plane Outbox: ip_outbox & ip_processed_events
    op.create_table(
        "ip_outbox",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("trace_id", sa.String(length=128), nullable=True),
        sa.Column("correlation_id", sa.String(length=255), nullable=True),
        sa.Column("lane", sa.String(length=32), server_default="realtime", nullable=False),
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
        ["status", "lane", "created_at"],
        postgresql_where=sa.text("status = 'PENDING'"),
    )

    op.create_table(
        "ip_processed_events",
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column(
            "processed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("idempotency_key"),
    )
    op.create_index(
        "idx_ip_processed_events_tenant",
        "ip_processed_events",
        ["tenant_id", "processed_at"],
    )

    op.create_table(
        "ip_batch_manifests",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("connection_id", sa.String(length=64), nullable=False),
        sa.Column("app_id", sa.String(length=64), server_default="", nullable=False),
        sa.Column("stream_name", sa.String(length=128), nullable=False),
        sa.Column(
            "priority_lane",
            sa.String(length=32),
            server_default="P1_LIVE",
            nullable=False,
        ),
        sa.Column(
            "payload_format",
            sa.String(length=32),
            server_default="JSON_ARRAY",
            nullable=False,
        ),
        sa.Column("status", sa.String(length=32), server_default="INGESTED", nullable=False),
        sa.Column("l1_raw_uri", sa.Text(), nullable=False),
        sa.Column("l2_replica_uri", sa.Text(), nullable=True),
        sa.Column("l3_canonical_uri", sa.Text(), nullable=True),
        sa.Column("inline_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("payload_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "payload_size_bytes", sa.BigInteger(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("window_start_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_ingested_count", sa.BigInteger(), nullable=False),
        sa.Column(
            "duplicates_dropped_count",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "valid_canonical_count",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "quarantined_held_count",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "promoted_outage_clusters_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("delivery_receipt_id", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("trace_id", sa.String(length=64), nullable=False),
        sa.Column("correlation_id", sa.String(length=255), nullable=True),
        sa.Column("parent_trace_id", sa.String(length=64), nullable=True),
        sa.Column("original_trace_id", sa.String(length=64), nullable=True),
        sa.Column("replay_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "connection_id",
            "payload_sha256",
            name="uq_ip_batch_manifests_sha256",
        ),
        sa.CheckConstraint(
            "status <> 'COMPLETED' OR raw_ingested_count = (duplicates_dropped_count + valid_canonical_count + quarantined_held_count)",
            name="chk_ip_batch_zero_loss_reconciliation",
        ),
    )
    op.create_index(
        "idx_ip_batch_manifests_tenant_conn",
        "ip_batch_manifests",
        ["tenant_id", "connection_id", "created_at"],
    )
    op.create_index(
        "idx_ip_batch_manifests_trace",
        "ip_batch_manifests",
        ["tenant_id", "trace_id"],
    )

    # 16. Layer 4: ip_replay_ledger (Universal Replay Audit Ledger)
    op.create_table(
        "ip_replay_ledger",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=False),
        sa.Column("target_id", sa.String(length=64), nullable=False),
        sa.Column("target_stage", sa.String(length=32), nullable=False),
        sa.Column("trace_id", sa.String(length=64), nullable=False),
        sa.Column("parent_trace_id", sa.String(length=64), nullable=False),
        sa.Column("original_trace_id", sa.String(length=64), nullable=True),
        sa.Column("correlation_id", sa.String(length=255), nullable=True),
        sa.Column("actor", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("payload_override", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("affected_records", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="IN_FLIGHT", nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_ip_replay_idempotency"),
    )
    op.create_index(
        "idx_ip_replay_target",
        "ip_replay_ledger",
        ["tenant_id", "target_type", "target_id"],
    )
    op.create_index(
        "idx_ip_replay_actor",
        "ip_replay_ledger",
        ["tenant_id", "actor", "created_at"],
    )
    op.create_index(
        "idx_ip_replay_trace",
        "ip_replay_ledger",
        ["tenant_id", "trace_id"],
    )
    op.create_index(
        "idx_ip_replay_status",
        "ip_replay_ledger",
        ["tenant_id", "status", "created_at"],
    )

    # 17. Durable Workflow: workflow_runs
    op.create_table(
        "workflow_runs",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("workflow_id", sa.String(length=128), nullable=False),
        sa.Column("workflow_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("priority", sa.SmallInteger(), server_default=sa.text("2"), nullable=False),
        sa.Column("concurrency_key", sa.String(length=255), nullable=True),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("parent_run_id", sa.String(length=64), nullable=True),
        sa.Column("trace_id", sa.String(length=64), nullable=False),
        sa.Column("correlation_id", sa.String(length=255), nullable=True),
        sa.Column("parent_trace_id", sa.String(length=64), nullable=True),
        sa.Column("original_trace_id", sa.String(length=64), nullable=True),
        sa.Column("replay_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("failure_code", sa.String(length=64), nullable=True),
        sa.Column("failure_detail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", "created_at"),
    )
    op.create_index(
        "idx_wf_runs_active_conc",
        "workflow_runs",
        ["tenant_id", "workflow_id", "concurrency_key"],
        postgresql_where=sa.text("status IN ('QUEUED', 'RUNNING', 'WAITING')"),
    )
    op.create_index("idx_wf_runs_trace", "workflow_runs", ["tenant_id", "trace_id"])
    op.create_index("idx_wf_runs_corr", "workflow_runs", ["tenant_id", "correlation_id"])
    op.create_index("idx_wf_runs_parent", "workflow_runs", ["tenant_id", "parent_run_id"])
    op.create_index("idx_wf_runs_orig_trace", "workflow_runs", ["tenant_id", "original_trace_id"])

    # 18. Durable Workflow: workflow_step_runs
    op.create_table(
        "workflow_step_runs",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("run_created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("node_key", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("retry_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("app_retry_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("internal_retry_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("iteration_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("failure_code", sa.String(length=64), nullable=True),
        sa.Column("failure_detail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", "created_at"),
        sa.UniqueConstraint("run_id", "node_key", "created_at", name="uq_wf_step_run_node"),
    )
    op.create_index("idx_wf_step_runs_run", "workflow_step_runs", ["tenant_id", "run_id"])

    # 19. Durable Workflow: workflow_active_leases
    op.create_table(
        "workflow_active_leases",
        sa.Column("step_run_id", sa.String(length=64), nullable=False),
        sa.Column("step_created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("worker_id", sa.String(length=128), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("timeout_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evicted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("step_run_id", "step_created_at", "retry_count"),
    )
    op.create_index("idx_wf_active_leases_expiry", "workflow_active_leases", ["lease_expires_at"])
    op.create_index("idx_wf_active_leases_timeout", "workflow_active_leases", ["timeout_at"])

    # 20. Durable Workflow: workflow_step_attempts
    op.create_table(
        "workflow_step_attempts",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("step_run_id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("app_retry_count", sa.Integer(), nullable=False),
        sa.Column("internal_retry_count", sa.Integer(), nullable=False),
        sa.Column("worker_id", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("is_app_error", sa.Boolean(), nullable=True),
        sa.Column("outcome_code", sa.String(length=64), nullable=True),
        sa.Column("outcome_detail", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", "started_at"),
    )
    op.create_index("idx_wf_step_attempts_step", "workflow_step_attempts", ["tenant_id", "step_run_id"])

    # 21. Durable Workflow: workflow_payloads
    op.create_table(
        "workflow_payloads",
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("owner_created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload_type", sa.String(length=32), nullable=False),
        sa.Column("location", sa.String(length=16), nullable=False),
        sa.Column("inline_content", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("external_ref", sa.String(length=512), nullable=True),
        sa.Column("payload_reference_id", sa.String(length=64), nullable=True),
        sa.Column("payload_reference_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("size_bytes", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "owner_id", "owner_created_at", "payload_type"),
    )

    # 22. Durable Workflow: workflow_idempotency_keys
    op.create_table(
        "workflow_idempotency_keys",
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("workflow_id", sa.String(length=128), nullable=False),
        sa.Column("key", sa.String(length=255), nullable=False),
        sa.Column("claimed_by_run_id", sa.String(length=64), nullable=False),
        sa.Column("eviction_policy", sa.String(length=32), server_default="TTL", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "workflow_id", "key"),
    )
    op.create_index("idx_wf_idempotency_expires", "workflow_idempotency_keys", ["expires_at"])

    # 23. Durable Workflow: workflow_matches
    op.create_table(
        "workflow_matches",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("step_run_id", sa.String(length=64), nullable=False),
        sa.Column("step_created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("node_key", sa.String(length=128), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column(
            "existing_data",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("is_satisfied", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("resolved_action", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_wf_matches_run", "workflow_matches", ["tenant_id", "run_id"])

    # 24. Durable Workflow: workflow_match_conditions
    op.create_table(
        "workflow_match_conditions",
        sa.Column("match_id", sa.String(length=64), nullable=False),
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("or_group_id", sa.String(length=64), nullable=False),
        sa.Column("condition_kind", sa.String(length=32), nullable=False),
        sa.Column("event_key", sa.String(length=128), nullable=False),
        sa.Column("event_resource_hint", sa.String(length=255), nullable=True),
        sa.Column("predicate_id", sa.String(length=128), nullable=True),
        sa.Column("readable_data_key", sa.String(length=128), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("is_satisfied", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("matched_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("timeout_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("match_id", "id"),
    )
    op.create_index(
        "idx_wf_match_cond_event",
        "workflow_match_conditions",
        ["tenant_id", "condition_kind", "event_key", "event_resource_hint"],
        postgresql_where=sa.text("NOT is_satisfied"),
    )
    op.create_index(
        "idx_wf_match_cond_timeout",
        "workflow_match_conditions",
        ["timeout_at"],
        postgresql_where=sa.text("NOT is_satisfied AND timeout_at IS NOT NULL"),
    )

    # 25. Durable Workflow: workflow_queue_items
    op.create_table(
        "workflow_queue_items",
        sa.Column("id", sa.BigInteger(), sa.Identity(start=1, cycle=False), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("step_run_id", sa.String(length=64), nullable=False),
        sa.Column("step_created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retry_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("item_kind", sa.String(length=32), nullable=False),
        sa.Column("queue_name", sa.String(length=64), nullable=False),
        sa.Column("priority", sa.SmallInteger(), server_default=sa.text("2"), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("enqueued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("concurrency_key", sa.String(length=255), nullable=True),
        sa.Column("rate_limit_key", sa.String(length=255), nullable=True),
        sa.Column("rate_limit_units", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_wf_queue_poll",
        "workflow_queue_items",
        ["queue_name", "available_at", "tenant_id", "priority", "id"],
    )

    # 26. Durable Workflow: workflow_paused_queue_items
    op.create_table(
        "workflow_paused_queue_items",
        sa.Column("id", sa.BigInteger(), sa.Identity(start=1, cycle=False), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("rate_limit_key", sa.String(length=255), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("step_run_id", sa.String(length=64), nullable=False),
        sa.Column("step_created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retry_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("queue_name", sa.String(length=64), nullable=False),
        sa.Column("priority", sa.SmallInteger(), server_default=sa.text("2"), nullable=False),
        sa.Column("requeue_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("concurrency_key", sa.String(length=255), nullable=True),
        sa.Column("rate_limit_units", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_wf_paused_queue_unpause",
        "workflow_paused_queue_items",
        ["requeue_after", "tenant_id", "rate_limit_key"],
    )

    # 27. Durable Workflow: workflow_queue_cursors
    op.create_table(
        "workflow_queue_cursors",
        sa.Column("queue_name", sa.String(length=64), nullable=False),
        sa.Column("last_serviced_tenant_id", sa.String(length=128), server_default="", nullable=False),
        sa.Column("min_unprocessed_id", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("queue_name"),
    )

    # 28. Durable Workflow: workflow_concurrency_slots
    op.create_table(
        "workflow_concurrency_slots",
        sa.Column("sort_id", sa.BigInteger(), sa.Identity(start=1, cycle=False), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("strategy_id", sa.String(length=64), nullable=False),
        sa.Column("concurrency_key", sa.String(length=255), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("step_run_id", sa.String(length=64), nullable=False),
        sa.Column("step_created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retry_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("priority", sa.SmallInteger(), server_default=sa.text("2"), nullable=False),
        sa.Column("is_filled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "next_strategy_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("queue_name", sa.String(length=64), server_default="default", nullable=False),
        sa.Column("rate_limit_key", sa.String(length=255), nullable=True),
        sa.Column("rate_limit_units", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("acquired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint(
            "sort_id",
            "tenant_id",
            "strategy_id",
            "step_run_id",
            "step_created_at",
            "retry_count",
        ),
    )
    op.create_index(
        "idx_wf_conc_slots_eval",
        "workflow_concurrency_slots",
        ["tenant_id", "strategy_id", "concurrency_key", "is_filled", "sort_id"],
    )

    # 29. Durable Workflow: workflow_rate_limit_buckets
    op.create_table(
        "workflow_rate_limit_buckets",
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("rate_limit_key", sa.String(length=255), nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=False),
        sa.Column("refill_per_second", sa.Float(), nullable=False),
        sa.Column("tokens", sa.Float(), nullable=False),
        sa.Column("refilled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paused_until", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("tenant_id", "rate_limit_key"),
    )

    # Enable Row-Level Security (RLS) across all tenant-scoped Engine Data Plane tables
    for table_name in (*_ENGINE_TABLES, *_ORCHESTRATION_TABLES_RLS):
        apply_tenant_isolation(op, table_name)


def downgrade() -> None:
    """Downgrade Engine Core Data Plane tables in tenant shard."""
    for table_name in reversed(_ORCHESTRATION_TABLES):
        op.drop_table(table_name, if_exists=True)
    for table_name in reversed(_ENGINE_TABLES):
        op.drop_table(table_name, if_exists=True)
