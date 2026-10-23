"""Application domain migration registry defining vertical domain schema branches."""

from __future__ import annotations

from pathlib import Path

import ip.application.domains.energy.models
import ip.application.domains.tms.models
from ip.engine.adapters.outbound.database.migrations.tenant.registry import (
    ENGINE_CORE,
    DomainMigrationModule,
)

_ENERGY_DIR = Path(ip.application.domains.energy.models.__file__).resolve().parent / "migrations"
ENERGY = DomainMigrationModule(
    branch_label="energy",
    orm_module=ip.application.domains.energy.models,
    versions_dir=_ENERGY_DIR,
    owned_tables=(
        "mdm_meter_readings",
        "mdm_service_points",
    ),
)

_TMS_DIR = Path(ip.application.domains.tms.models.__file__).resolve().parent / "migrations"
TMS = DomainMigrationModule(
    branch_label="tms",
    orm_module=ip.application.domains.tms.models,
    versions_dir=_TMS_DIR,
    owned_tables=(
        "tms_loads",
        "tms_carriers",
    ),
)

DOMAIN_MIGRATION_MODULES: tuple[DomainMigrationModule, ...] = (
    ENGINE_CORE,
    ENERGY,
    TMS,
)

__all__ = [
    "DOMAIN_MIGRATION_MODULES",
    "ENERGY",
    "TMS",
]
