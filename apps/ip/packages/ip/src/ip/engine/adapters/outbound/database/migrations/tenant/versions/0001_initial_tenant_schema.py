"""Initial Data Plane & Canonical Domain schema for Integration Platform (tenant shards).

Revision ID: 0001_initial_tenant_schema
Revises:
Create Date: 2026-10-22 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001_initial_tenant_schema"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT_RLS_TABLES: tuple[str, ...] = (
    "inbound_records",
    "outbound_records",
    "replica_records",
    "normalized_records",
    "global_entity_map",
    "ip_trace_events",
    "ip_outbox",
    "mdm_meter_readings",
    "mdm_service_points",
    "tms_loads",
    "tms_carriers",
)


def upgrade() -> None:
    """Upgrade Data Plane & Canonical Domain tables in tenant shard."""
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
    )
    op.create_index("idx_outbound_trace", "outbound_records", ["tenant_id", "trace_id"])
    op.create_index("idx_outbound_corr", "outbound_records", ["tenant_id", "correlation_id"])
    op.create_index("idx_outbound_conn", "outbound_records", ["tenant_id", "connection_id"])
    op.create_index("idx_outbound_app", "outbound_records", ["tenant_id", "app_id"])
    op.create_index("idx_outbound_status", "outbound_records", ["tenant_id", "status"])

    # 3. Layer 2: replica_records
    op.create_table(
        "replica_records",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("connection_id", sa.String(length=64), nullable=False),
        sa.Column("app_id", sa.String(length=64), nullable=False),
        sa.Column("entity_type", sa.String(length=128), nullable=False),
        sa.Column("entity_id", sa.String(length=255), nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("data_hash", sa.String(length=64), nullable=False),
        sa.Column("trace_id", sa.String(length=64), nullable=False),
        sa.Column("correlation_id", sa.String(length=255), nullable=True),
        sa.Column("parent_trace_id", sa.String(length=64), nullable=True),
        sa.Column("original_trace_id", sa.String(length=64), nullable=True),
        sa.Column("replay_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("version", sa.BigInteger(), server_default=sa.text("1"), nullable=False),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "connection_id",
            "entity_type",
            "entity_id",
            name="uq_ip_replica_record_identity",
        ),
    )
    op.create_index("idx_replica_tenant_entity", "replica_records", ["tenant_id", "entity_type"])
    op.create_index("idx_replica_data_hash", "replica_records", ["tenant_id", "data_hash"])
    op.create_index("idx_replica_trace", "replica_records", ["tenant_id", "trace_id"])
    op.create_index("idx_replica_corr", "replica_records", ["tenant_id", "correlation_id"])

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

    # 6. Application Canonical Domain Tables: Energy MDM (mdm_meter_readings, mdm_service_points)
    op.create_table(
        "mdm_meter_readings",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("trace_id", sa.String(length=64), nullable=False),
        sa.Column("correlation_id", sa.String(length=255), nullable=True),
        sa.Column("parent_trace_id", sa.String(length=64), nullable=True),
        sa.Column("original_trace_id", sa.String(length=64), nullable=True),
        sa.Column("replay_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("source_connection_id", sa.String(length=64), nullable=False),
        sa.Column("source_replica_id", sa.String(length=64), nullable=False),
        sa.Column("meter_serial_number", sa.String(length=128), nullable=False),
        sa.Column("service_point_id", sa.String(length=128), nullable=True),
        sa.Column("reading_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("interval_minutes", sa.Integer(), server_default=sa.text("15"), nullable=False),
        sa.Column("kwh_delivered", sa.Float(), nullable=False),
        sa.Column("kwh_received", sa.Float(), server_default=sa.text("0.0"), nullable=False),
        sa.Column("voltage_avg", sa.Float(), nullable=True),
        sa.Column("quality_flag", sa.String(length=32), server_default="VALIDATED", nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", "reading_timestamp"),
    )
    op.create_index(
        "idx_mdm_readings_meter_ts",
        "mdm_meter_readings",
        ["tenant_id", "meter_serial_number", "reading_timestamp"],
    )
    op.create_index("idx_mdm_readings_sp", "mdm_meter_readings", ["tenant_id", "service_point_id"])
    op.create_index("idx_mdm_readings_trace", "mdm_meter_readings", ["tenant_id", "trace_id"])

    op.create_table(
        "mdm_service_points",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("trace_id", sa.String(length=64), nullable=False),
        sa.Column("correlation_id", sa.String(length=255), nullable=True),
        sa.Column("parent_trace_id", sa.String(length=64), nullable=True),
        sa.Column("original_trace_id", sa.String(length=64), nullable=True),
        sa.Column("replay_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("source_connection_id", sa.String(length=64), nullable=False),
        sa.Column("source_replica_id", sa.String(length=64), nullable=False),
        sa.Column("service_point_external_id", sa.String(length=128), nullable=False),
        sa.Column("meter_serial_number", sa.String(length=128), nullable=True),
        sa.Column("customer_external_id", sa.String(length=128), nullable=True),
        sa.Column("service_address", sa.String(length=512), nullable=True),
        sa.Column("grid_region", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), server_default="ACTIVE", nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "service_point_external_id",
            name="uq_mdm_service_point_tenant_ext",
        ),
    )
    op.create_index("idx_mdm_sp_meter", "mdm_service_points", ["tenant_id", "meter_serial_number"])
    op.create_index("idx_mdm_sp_trace", "mdm_service_points", ["tenant_id", "trace_id"])

    # 7. Application Canonical Domain Tables: TMS (tms_loads, tms_carriers)
    op.create_table(
        "tms_loads",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("trace_id", sa.String(length=64), nullable=False),
        sa.Column("correlation_id", sa.String(length=255), nullable=True),
        sa.Column("parent_trace_id", sa.String(length=64), nullable=True),
        sa.Column("original_trace_id", sa.String(length=64), nullable=True),
        sa.Column("replay_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("source_connection_id", sa.String(length=64), nullable=False),
        sa.Column("source_replica_id", sa.String(length=64), nullable=False),
        sa.Column("load_reference_number", sa.String(length=128), nullable=False),
        sa.Column("carrier_scac", sa.String(length=32), nullable=True),
        sa.Column("origin_city", sa.String(length=128), nullable=False),
        sa.Column("origin_state", sa.String(length=64), nullable=False),
        sa.Column("destination_city", sa.String(length=128), nullable=False),
        sa.Column("destination_state", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="TENDERED", nullable=False),
        sa.Column("total_weight_lbs", sa.Float(), server_default=sa.text("0.0"), nullable=False),
        sa.Column("freight_charge_usd", sa.Float(), server_default=sa.text("0.0"), nullable=False),
        sa.Column("pickup_scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivery_scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "load_reference_number",
            name="uq_tms_loads_tenant_ref",
        ),
    )
    op.create_index("idx_tms_loads_carrier", "tms_loads", ["tenant_id", "carrier_scac"])
    op.create_index("idx_tms_loads_status", "tms_loads", ["tenant_id", "status"])
    op.create_index("idx_tms_loads_trace", "tms_loads", ["tenant_id", "trace_id"])

    op.create_table(
        "tms_carriers",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("trace_id", sa.String(length=64), nullable=False),
        sa.Column("correlation_id", sa.String(length=255), nullable=True),
        sa.Column("parent_trace_id", sa.String(length=64), nullable=True),
        sa.Column("original_trace_id", sa.String(length=64), nullable=True),
        sa.Column("replay_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("source_connection_id", sa.String(length=64), nullable=False),
        sa.Column("source_replica_id", sa.String(length=64), nullable=False),
        sa.Column("scac_code", sa.String(length=32), nullable=False),
        sa.Column("carrier_name", sa.String(length=255), nullable=False),
        sa.Column("dot_number", sa.String(length=64), nullable=True),
        sa.Column("mc_number", sa.String(length=64), nullable=True),
        sa.Column("safety_rating", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), server_default="ACTIVE", nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "scac_code",
            name="uq_tms_carriers_tenant_scac",
        ),
    )
    op.create_index("idx_tms_carriers_status", "tms_carriers", ["tenant_id", "status"])
    op.create_index("idx_tms_carriers_trace", "tms_carriers", ["tenant_id", "trace_id"])

    # Enable Row-Level Security (RLS) across all tenant-scoped Data Plane & Canonical Domain tables
    for table_name in _TENANT_RLS_TABLES:
        op.execute(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY;")
        op.execute(
            f"CREATE POLICY tenant_isolation_{table_name} ON {table_name} "
            "USING (tenant_id = current_setting('platform.current_tenant_id', true));"
        )


def downgrade() -> None:
    """Downgrade Data Plane & Canonical Domain tables in tenant shard."""
    for table_name in reversed(_TENANT_RLS_TABLES):
        op.drop_table(table_name, if_exists=True)
