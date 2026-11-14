"""Universal Schema Simulator table (`ip.simulator_entities`) in `global_db`.

Revision ID: 0001_universal_simulator_schema
Revises:
Create Date: 2026-11-11 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_universal_simulator_schema"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ("universal_simulator",)
depends_on: str | Sequence[str] | None = "0001_initial_global_schema"


def upgrade() -> None:
    """Create `ip.simulator_entities` in `global_db`."""
    op.create_table(
        "simulator_entities",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("connection_id", sa.String(length=64), nullable=False),
        sa.Column("entity_name", sa.String(length=128), nullable=False),
        sa.Column("primary_key_field", sa.String(length=128), nullable=False),
        sa.Column("cursor_field", sa.String(length=128), nullable=False),
        sa.Column(
            "push_mode",
            sa.String(length=32),
            server_default="RANDOM_BURST",
            nullable=False,
        ),
        sa.Column(
            "push_config",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "records_per_pull",
            sa.Integer(),
            server_default=sa.text("25"),
            nullable=False,
        ),
        sa.Column(
            "cursor_step_seconds",
            sa.Integer(),
            server_default=sa.text("60"),
            nullable=False,
        ),
        sa.Column(
            "velocity_mode",
            sa.String(length=32),
            server_default="ENTITY_TRANSACTIONAL",
            nullable=False,
        ),
        sa.Column(
            "sample_blueprint",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "inferred_json_schema",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "chaos_policy",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "version",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
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
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["ip.connections.id"],
            name="fk_ip_simulator_entities_connection_id",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "connection_id",
            "entity_name",
            name="uq_ip_simulator_entity_conn_name",
        ),
        schema="ip",
    )
    op.create_index(
        "idx_ip_simulator_entities_tenant_conn",
        "simulator_entities",
        ["tenant_id", "connection_id"],
        unique=False,
        schema="ip",
    )


def downgrade() -> None:
    """Drop `ip.simulator_entities`."""
    op.drop_index(
        "idx_ip_simulator_entities_tenant_conn",
        table_name="simulator_entities",
        schema="ip",
    )
    op.drop_table("simulator_entities", schema="ip")
