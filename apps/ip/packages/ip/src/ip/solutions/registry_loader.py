"""Default L4 Stitch WorkflowDefinition and Stitch registry loader across all domain bounded contexts."""

from __future__ import annotations

from orchestration.application.services import InMemoryWorkflowDefinitionRegistry
from orchestration.domain.definition import WorkflowDefinition
from orchestration.ports.inbound.step_handler_port import WorkflowDefinitionRegistryPort

from ip.engine.domain.stitch.stitch import Stitch
from ip.engine.ports.outbound.stitch_catalog_registry_port import (
    StitchCatalogRegistryPort,
)
from ip.solutions.domains.energy.stitches import (
    build_energy_stitch_definitions,
    build_energy_stitches,
)
from ip.solutions.domains.tms.stitches import (
    build_tms_stitch_definitions,
    build_tms_stitches,
)


def build_default_stitch_definitions() -> tuple[WorkflowDefinition, ...]:
    """Return built-in static DAG WorkflowDefinitions for Energy and TMS verticals."""
    return (
        *build_energy_stitch_definitions(),
        *build_tms_stitch_definitions(),
    )


def build_default_stitches() -> tuple[Stitch, ...]:
    """Return built-in wildcard Stitches connecting canonical events to workflows."""
    return (
        *build_energy_stitches(),
        *build_tms_stitches(),
    )


def register_default_stitch_definitions(registry: WorkflowDefinitionRegistryPort) -> None:
    """Register all built-in Stitch WorkflowDefinitions into the provided registry."""
    for defn in build_default_stitch_definitions():
        registry.register(defn)


def register_default_stitches(registry: StitchCatalogRegistryPort) -> None:
    """Register all built-in Stitches into the provided stitch catalog registry."""
    for stitch in build_default_stitches():
        registry.register_stitch(stitch)


def create_default_workflow_definition_registry() -> InMemoryWorkflowDefinitionRegistry:
    """Create and populate an InMemoryWorkflowDefinitionRegistry with built-in stitch DAGs."""
    registry = InMemoryWorkflowDefinitionRegistry()
    register_default_stitch_definitions(registry)
    return registry


__all__ = [
    "build_default_stitch_definitions",
    "build_default_stitches",
    "create_default_workflow_definition_registry",
    "register_default_stitch_definitions",
    "register_default_stitches",
]
