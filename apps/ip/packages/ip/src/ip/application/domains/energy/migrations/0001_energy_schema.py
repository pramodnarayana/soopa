"""Energy MDM domain schema for Integration Platform (tenant shards).

Revision ID: 0001_energy_schema
Revises:
Create Date: 2026-10-22 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from ip.engine.adapters.outbound.database.isolation import apply_tenant_isolation

# revision identifiers, used by Alembic.
revision: str = "0001_energy_schema"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ("energy",)
depends_on: str | Sequence[str] | None = "0001_engine_core_schema"

_ENERGY_TABLES: tuple[str, ...] = (
    "mdm_meter_readings",
    "mdm_service_points",
)


def upgrade() -> None:
    """Upgrade Energy MDM domain tables in tenant shard."""
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
        sa.Column(
            "transformation_id",
            sa.String(length=128),
            server_default="energy.ami_meter_reading",
            nullable=False,
        ),
        sa.Column(
            "transformation_version",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
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
        sa.Column(
            "transformation_id",
            sa.String(length=128),
            server_default="energy.ami_service_point",
            nullable=False,
        ),
        sa.Column(
            "transformation_version",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
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

    for table_name in _ENERGY_TABLES:
        apply_tenant_isolation(op, table_name)


def downgrade() -> None:
    """Downgrade Energy MDM domain tables in tenant shard."""
    for table_name in reversed(_ENERGY_TABLES):
        op.drop_table(table_name, if_exists=True)
