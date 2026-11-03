"""TMS domain schema for Integration Platform (tenant shards).

Revision ID: 0001_tms_schema
Revises:
Create Date: 2026-10-22 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from ip.engine.adapters.outbound.database.isolation import apply_tenant_isolation

# revision identifiers, used by Alembic.
revision: str = "0001_tms_schema"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ("tms",)
depends_on: str | Sequence[str] | None = "0001_engine_core_schema"

_TMS_TABLES: tuple[str, ...] = (
    "tms_loads",
    "tms_carriers",
)


def upgrade() -> None:
    """Upgrade TMS domain tables in tenant shard."""
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
        sa.Column(
            "freight_charge_usd",
            sa.Numeric(precision=14, scale=2),
            server_default=sa.text("0.00"),
            nullable=False,
        ),
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

    for table_name in _TMS_TABLES:
        apply_tenant_isolation(op, table_name)


def downgrade() -> None:
    """Downgrade TMS domain tables in tenant shard."""
    for table_name in reversed(_TMS_TABLES):
        op.drop_table(table_name, if_exists=True)
