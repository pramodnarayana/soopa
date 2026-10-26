"""Engine database migration registry defining the engine's core Data Plane migration module."""

from __future__ import annotations

from pathlib import Path

import ip.engine.adapters.outbound.database.models.data_plane
from ip.engine.ports.outbound.domain_migration_port import DomainMigrationModule

_BASE_DIR = Path(__file__).resolve().parent

ENGINE_CORE = DomainMigrationModule(
    branch_label="engine",
    orm_module=ip.engine.adapters.outbound.database.models.data_plane,
    versions_dir=_BASE_DIR / "versions",
    owned_tables=(
        "inbound_records",
        "replica_records",
        "replica_rejections",
        "normalized_records",
        "normalization_ledger",
        "normalization_rejections",
        "normalization_shadow_diffs",
        "pending_references",
        "global_entity_map",
        "outbound_records",
        "ip_trace_events",
        "ip_outbox",
    ),
)

__all__ = [
    "ENGINE_CORE",
    "DomainMigrationModule",
]
