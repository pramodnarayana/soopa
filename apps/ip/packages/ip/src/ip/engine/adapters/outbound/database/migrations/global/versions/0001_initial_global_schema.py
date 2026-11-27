"""Initial Control Plane schema for Integration Platform (IP - global_db, schema 'ip').

Revision ID: 0001_initial_global_schema
Revises:
Create Date: 2026-10-18 19:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from identity.domain.identity_context import PLATFORM_TENANT_ID
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001_initial_global_schema"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ("global_engine",)
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade Control Plane schema in global_db."""
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
        sa.CheckConstraint(
            "NOT (auth_type = 'NO_AUTH' AND status = 'PENDING_AUTH')",
            name="ck_ip_connections_no_auth_not_pending",
        ),
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
        "outbox",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
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
        ["status", "lane", "created_at"],
        unique=False,
        postgresql_where=sa.text("status = 'PENDING'"),
        schema="ip",
    )
    op.create_table(
        "connection_entities",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("connection_id", sa.String(length=64), nullable=False),
        sa.Column("stream_name", sa.String(length=128), nullable=False),
        sa.Column(
            "sync_mode",
            sa.String(length=32),
            server_default="INCREMENTAL",
            nullable=False,
        ),
        sa.Column(
            "schedule",
            sa.String(length=32),
            server_default="manual",
            nullable=False,
        ),
        sa.Column(
            "sync_from",
            sa.String(length=32),
            server_default="all",
            nullable=False,
        ),
        sa.Column("sync_from_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "is_enabled",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "primary_key",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "fields_schema",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("cursor_field", sa.String(length=128), nullable=True),
        sa.Column("cursor_value", sa.Text(), nullable=True),
        sa.Column(
            "records_synced_count", sa.BigInteger(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["ip.connections.id"],
            name="fk_ip_connection_entities_connection_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "connection_id",
            "stream_name",
            name="uq_ip_connection_entities_tenant_conn_stream",
        ),
        schema="ip",
    )
    op.create_index(
        "idx_ip_connection_entities_conn",
        "connection_entities",
        ["tenant_id", "connection_id"],
        unique=False,
        schema="ip",
    )
    op.create_index(
        "idx_ip_connection_entities_due_schedule",
        "connection_entities",
        ["schedule"],
        unique=False,
        postgresql_where=sa.text("is_enabled = true AND schedule != 'manual'"),
        schema="ip",
    )
    op.create_table(
        "sync_runs",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("connection_id", sa.String(length=64), nullable=False),
        sa.Column("stream", sa.String(length=128), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("generation_id", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default="PENDING",
            nullable=False,
        ),
        sa.Column("start_checkpoint", sa.Text(), nullable=True),
        sa.Column("end_checkpoint", sa.Text(), nullable=True),
        sa.Column("pages_synced", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("records_synced", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("bytes_synced", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("retries_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("trace_id", sa.String(length=64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["ip.connections.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="ip",
    )
    op.create_index(
        "uq_ip_sync_runs_active_stream",
        "sync_runs",
        ["connection_id", "stream"],
        unique=True,
        postgresql_where=sa.text("status IN ('PENDING', 'RUNNING')"),
        schema="ip",
    )
    op.create_index(
        "idx_ip_sync_runs_tenant_conn",
        "sync_runs",
        ["tenant_id", "connection_id"],
        unique=False,
        schema="ip",
    )
    op.create_index(
        "idx_ip_sync_runs_status",
        "sync_runs",
        ["status", "created_at"],
        unique=False,
        schema="ip",
    )

    op.create_table(
        "transformations",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("connection_id", sa.String(length=64), nullable=False),
        sa.Column("stream", sa.String(length=128), nullable=False),
        sa.Column("transformation_id", sa.String(length=128), nullable=False),
        sa.Column(
            "transformation_version",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column("shadow_transformation_version", sa.Integer(), nullable=True),
        sa.Column(
            "mode",
            sa.String(length=32),
            server_default="ACTIVE",
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["ip.connections.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "connection_id", "stream", name="uq_ip_transformation_stream"
        ),
        schema="ip",
    )
    op.create_index(
        "ix_ip_transformations_conn",
        "transformations",
        ["connection_id"],
        unique=False,
        schema="ip",
    )

    op.create_table(
        "mapping_specs",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("source_type", sa.String(length=128), nullable=False),
        sa.Column("target_connection_id", sa.String(length=64), nullable=False),
        sa.Column("target_entity_name", sa.String(length=128), nullable=False),
        sa.Column(
            "version",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column(
            "rules",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["target_connection_id"],
            ["ip.connections.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "target_connection_id",
            "target_entity_name",
            "version",
            name="uq_ip_mapping_specs_tenant_target_version",
        ),
        schema="ip",
    )
    op.create_index(
        "idx_ip_mapping_specs_lookup",
        "mapping_specs",
        ["tenant_id", "source_type", "target_connection_id"],
        unique=False,
        schema="ip",
    )

    op.create_table(
        "stitches",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("canonical_event_type", sa.String(length=128), nullable=False),
        sa.Column("target_workflow_id", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=255), server_default="", nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("mapping_spec_id", sa.String(length=64), nullable=True),
        sa.Column(
            "filter_conditions",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["mapping_spec_id"],
            ["ip.mapping_specs.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", "tenant_id"),
        schema="ip",
    )
    op.create_index(
        "ix_ip_stitches_tenant_event",
        "stitches",
        ["tenant_id", "canonical_event_type"],
        unique=False,
        schema="ip",
    )
    op.create_index(
        "ix_ip_stitches_target_workflow",
        "stitches",
        ["target_workflow_id"],
        unique=False,
        schema="ip",
    )
    op.create_index(
        "uq_ip_stitches_concrete_id",
        "stitches",
        ["id"],
        unique=True,
        postgresql_where=sa.column("tenant_id") != sa.literal(PLATFORM_TENANT_ID),
        schema="ip",
    )

    op.create_table(
        "webhook_endpoints",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("endpoint_slug", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "verification_strategy",
            sa.String(length=32),
            server_default="SHARED_HEADER_SECRET",
            nullable=False,
        ),
        sa.Column("primary_secret_hash", sa.String(length=255), nullable=False),
        sa.Column("secondary_secret_hash", sa.String(length=255), nullable=True),
        sa.Column("secret_rotated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("bound_connection_id", sa.String(length=64), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["bound_connection_id"],
            ["ip.connections.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "endpoint_slug", name="uq_tenant_endpoint_slug"),
        schema="ip",
    )
    op.create_index(
        "idx_webhook_slug_lookup",
        "webhook_endpoints",
        ["tenant_id", "endpoint_slug"],
        unique=False,
        schema="ip",
        postgresql_where=sa.text("is_active = TRUE"),
    )
    op.create_index(
        op.f("ix_ip_webhook_endpoints_tenant_id"),
        "webhook_endpoints",
        ["tenant_id"],
        unique=False,
        schema="ip",
    )

    op.create_table(
        "webhook_event_routes",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("endpoint_id", sa.String(length=64), nullable=False),
        sa.Column("event_pattern", sa.String(length=128), nullable=False),
        sa.Column("payload_semantic", sa.String(length=32), server_default="DATA", nullable=False),
        sa.Column("target_pipeline_or_workflow_id", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("priority", sa.Integer(), server_default=sa.text("100"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["endpoint_id"],
            ["ip.webhook_endpoints.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("endpoint_id", "event_pattern", name="uq_endpoint_event_pattern"),
        schema="ip",
    )
    op.create_index(
        "idx_event_route_lookup",
        "webhook_event_routes",
        ["endpoint_id", "priority"],
        unique=False,
        schema="ip",
        postgresql_where=sa.text("is_active = TRUE"),
    )

    op.create_table(
        "connection_policies",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("connection_id", sa.String(length=64), nullable=False),
        sa.Column(
            "max_query_window_days",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column("max_query_window_hours", sa.Integer(), nullable=True),
        sa.Column(
            "min_query_window_minutes",
            sa.Integer(),
            server_default=sa.text("15"),
            nullable=False,
        ),
        sa.Column(
            "max_entities_per_call",
            sa.Integer(),
            server_default=sa.text("100"),
            nullable=False,
        ),
        sa.Column(
            "max_records_per_batch",
            sa.Integer(),
            server_default=sa.text("10000"),
            nullable=False,
        ),
        sa.Column(
            "supports_wildcard_queries",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "max_concurrency",
            sa.Integer(),
            server_default=sa.text("2"),
            nullable=False,
        ),
        sa.Column(
            "rate_limit_rpm",
            sa.Integer(),
            server_default=sa.text("60"),
            nullable=False,
        ),
        sa.Column(
            "cooldown_seconds_between_calls",
            sa.Float(),
            server_default=sa.text("0.0"),
            nullable=False,
        ),
        sa.Column("blackout_cron_schedule", sa.String(length=64), nullable=True),
        sa.Column(
            "blackout_duration_minutes",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "vendor_quirks",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "is_enabled",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["ip.connections.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("connection_id", name="uq_ip_conn_policies_conn_id"),
        sa.CheckConstraint("max_query_window_days > 0", name="chk_ip_cpol_window_days"),
        sa.CheckConstraint("max_concurrency > 0", name="chk_ip_cpol_concurrency"),
        sa.CheckConstraint("rate_limit_rpm > 0", name="chk_ip_cpol_rpm"),
        schema="ip",
    )
    op.create_index(
        "idx_ip_conn_policies_lookup",
        "connection_policies",
        ["tenant_id", "connection_id"],
        unique=False,
        schema="ip",
    )

    op.create_table(
        "stitch_task_configs",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("stitch_id", sa.String(length=64), nullable=False),
        sa.Column("node_key", sa.String(length=64), nullable=False),
        sa.Column(
            "timeout_seconds",
            sa.Integer(),
            server_default=sa.text("60"),
            nullable=False,
        ),
        sa.Column(
            "heartbeat_interval_seconds",
            sa.Integer(),
            server_default=sa.text("15"),
            nullable=False,
        ),
        sa.Column(
            "max_attempts",
            sa.Integer(),
            server_default=sa.text("5"),
            nullable=False,
        ),
        sa.Column(
            "initial_delay_seconds",
            sa.Float(),
            server_default=sa.text("2.0"),
            nullable=False,
        ),
        sa.Column(
            "backoff_multiplier",
            sa.Float(),
            server_default=sa.text("2.0"),
            nullable=False,
        ),
        sa.Column(
            "max_delay_seconds",
            sa.Float(),
            server_default=sa.text("60.0"),
            nullable=False,
        ),
        sa.Column(
            "queue_name",
            sa.String(length=64),
            server_default="default",
            nullable=False,
        ),
        sa.Column(
            "max_in_flight_tasks",
            sa.Integer(),
            server_default=sa.text("3"),
            nullable=False,
        ),
        sa.Column(
            "failure_disposition",
            sa.String(length=32),
            server_default="RETRY_THEN_QUARANTINE",
            nullable=False,
        ),
        sa.Column(
            "quarantine_stream_name",
            sa.String(length=128),
            server_default="dead_letter_records",
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["stitch_id", "tenant_id"],
            ["ip.stitches.id", "ip.stitches.tenant_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "stitch_id",
            "node_key",
            name="uq_ip_stitch_task_config_node",
        ),
        schema="ip",
    )
    op.create_index(
        "idx_ip_stitch_task_configs_lookup",
        "stitch_task_configs",
        ["tenant_id", "stitch_id", "node_key"],
        unique=False,
        schema="ip",
    )


def downgrade() -> None:
    """Downgrade Control Plane schema."""
    op.drop_index(
        "idx_event_route_lookup",
        table_name="webhook_event_routes",
        schema="ip",
        if_exists=True,
    )
    op.drop_table("webhook_event_routes", schema="ip", if_exists=True)
    op.drop_index(
        op.f("ix_ip_webhook_endpoints_tenant_id"),
        table_name="webhook_endpoints",
        schema="ip",
        if_exists=True,
    )
    op.drop_index(
        "idx_webhook_slug_lookup",
        table_name="webhook_endpoints",
        schema="ip",
        if_exists=True,
    )
    op.drop_table("webhook_endpoints", schema="ip", if_exists=True)
    op.drop_index(
        "idx_ip_stitch_task_configs_lookup",
        table_name="stitch_task_configs",
        schema="ip",
        if_exists=True,
    )
    op.drop_table("stitch_task_configs", schema="ip", if_exists=True)
    op.drop_index(
        "uq_ip_stitches_concrete_id",
        table_name="stitches",
        schema="ip",
        if_exists=True,
    )
    op.drop_index(
        "ix_ip_stitches_target_workflow",
        table_name="stitches",
        schema="ip",
        if_exists=True,
    )
    op.drop_index(
        "ix_ip_stitches_tenant_event",
        table_name="stitches",
        schema="ip",
        if_exists=True,
    )
    op.drop_table("stitches", schema="ip", if_exists=True)
    op.drop_index(
        "idx_ip_mapping_specs_lookup",
        table_name="mapping_specs",
        schema="ip",
        if_exists=True,
    )
    op.drop_table("mapping_specs", schema="ip", if_exists=True)
    op.drop_index(
        "ix_ip_transformations_conn",
        table_name="transformations",
        schema="ip",
        if_exists=True,
    )
    op.drop_table("transformations", schema="ip", if_exists=True)
    op.drop_index(
        "idx_ip_sync_runs_status",
        table_name="sync_runs",
        schema="ip",
        if_exists=True,
    )
    op.drop_index(
        "idx_ip_sync_runs_tenant_conn",
        table_name="sync_runs",
        schema="ip",
        if_exists=True,
    )
    op.drop_index(
        "uq_ip_sync_runs_active_stream",
        table_name="sync_runs",
        schema="ip",
        if_exists=True,
    )
    op.drop_table("sync_runs", schema="ip", if_exists=True)
    op.drop_index(
        "idx_ip_connection_entities_due_schedule",
        table_name="connection_entities",
        schema="ip",
        if_exists=True,
    )
    op.drop_index(
        "idx_ip_connection_entities_conn",
        table_name="connection_entities",
        schema="ip",
        if_exists=True,
    )
    op.drop_table("connection_entities", schema="ip", if_exists=True)
    op.drop_index(
        "ix_ip_outbox_pending",
        table_name="outbox",
        schema="ip",
        if_exists=True,
    )
    op.drop_index(
        op.f("ix_ip_outbox_tenant_id"),
        table_name="outbox",
        schema="ip",
        if_exists=True,
    )
    op.drop_table("outbox", schema="ip", if_exists=True)
    op.drop_index(
        "idx_ip_conn_policies_lookup",
        table_name="connection_policies",
        schema="ip",
        if_exists=True,
    )
    op.drop_table("connection_policies", schema="ip", if_exists=True)
    op.drop_index(
        op.f("ix_ip_connections_tenant_id"),
        table_name="connections",
        schema="ip",
        if_exists=True,
    )
    op.drop_index(
        "uq_tenant_active_fingerprint",
        table_name="connections",
        schema="ip",
        if_exists=True,
    )
    op.drop_table("connections", schema="ip", if_exists=True)
