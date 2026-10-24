"""Port defining the DomainMigrationModule contract for Data Plane shard migrations."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import ModuleType


@dataclass(frozen=True)
class DomainMigrationModule:
    """Represents a pluggable vertical domain's migration branch on the Data Plane shard."""

    branch_label: str
    orm_module: ModuleType
    versions_dir: Path
    owned_tables: tuple[str, ...]


__all__ = ["DomainMigrationModule"]
