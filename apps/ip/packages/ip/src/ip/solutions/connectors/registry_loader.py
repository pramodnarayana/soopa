"""Loader routines registering built-in SaaS manifests and vertical sandbox connectors onto a CatalogRegistryPort."""

from __future__ import annotations

from ip.engine.ports.outbound.catalog_registry_port import CatalogRegistryPort
from ip.solutions.connectors.manifests import BUILTIN_MANIFESTS
from ip.solutions.connectors.sandbox.energy.ami_simulator_connector import (
    EnergyAmiSimulatorConnector,
)
from ip.solutions.connectors.sandbox.universal.connector import (
    UniversalSchemaSimulatorConnector,
)


def register_solution_connectors(registry: CatalogRegistryPort) -> None:
    """Registers built-in declarative SaaS manifests and sandbox simulators onto `registry`."""
    for manifest in BUILTIN_MANIFESTS:
        registry.register_manifest(manifest)

    ami_simulator = EnergyAmiSimulatorConnector()
    registry.register_connector(
        ami_simulator,
        EnergyAmiSimulatorConnector.default_catalog_summary(),
    )

    universal_simulator = UniversalSchemaSimulatorConnector()
    registry.register_connector(
        universal_simulator,
        UniversalSchemaSimulatorConnector.default_catalog_summary(),
    )


__all__ = ["register_solution_connectors"]
