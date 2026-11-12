"""Loader routines registering built-in SaaS manifests and vertical sandbox connectors onto a CatalogRegistryPort."""

from __future__ import annotations

from ip.engine.ports.outbound.catalog_registry_port import CatalogRegistryPort
from ip.solutions.connectors.manifests import BUILTIN_MANIFESTS
from ip.solutions.connectors.sandbox.universal.connector import (
    UniversalSchemaSimulatorConnector,
)
from ip.solutions.connectors.sandbox.universal.ports import SimulatorEntityReaderPort


def register_solution_connectors(
    registry: CatalogRegistryPort,
    *,
    entity_reader: SimulatorEntityReaderPort | None = None,
) -> None:
    """Registers built-in declarative SaaS manifests and sandbox simulators onto `registry`."""
    for manifest in BUILTIN_MANIFESTS:
        registry.register_manifest(manifest)

    universal_simulator = UniversalSchemaSimulatorConnector(entity_reader=entity_reader)
    registry.register_connector(
        universal_simulator,
        UniversalSchemaSimulatorConnector.default_catalog_summary(),
    )


__all__ = ["register_solution_connectors"]
