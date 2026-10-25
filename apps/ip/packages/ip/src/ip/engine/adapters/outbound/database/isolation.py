"""Tenant isolation helpers for PostgreSQL Row Level Security (RLS)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from alembic.operations import Operations


def apply_tenant_isolation(op: Operations, table_name: str) -> None:
    """Enables PostgreSQL Row-Level Security and creates the tenant isolation policy on table_name."""
    op.execute(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY;")
    op.execute(
        f"CREATE POLICY tenant_isolation_{table_name} ON {table_name} "
        "USING (tenant_id = current_setting('platform.current_tenant_id', true));"
    )


def drop_tenant_isolation(op: Operations, table_name: str) -> None:
    """Drops the tenant isolation policy and disables PostgreSQL Row-Level Security on table_name."""
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation_{table_name} ON {table_name};")
    op.execute(f"ALTER TABLE {table_name} DISABLE ROW LEVEL SECURITY;")


__all__ = [
    "apply_tenant_isolation",
    "drop_tenant_isolation",
]
