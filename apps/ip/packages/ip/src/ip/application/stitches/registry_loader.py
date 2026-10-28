"""Default L4 Stitch WorkflowDefinition and Stitch registry loader."""

from __future__ import annotations

from datetime import timedelta

from orchestration.application.services import InMemoryWorkflowDefinitionRegistry
from orchestration.domain.constants import EffectPolicy, NodeKind, Priority
from orchestration.domain.definition import (
    NodeDefinition,
    WaitEventSpec,
    WorkflowDefinition,
)
from orchestration.ports.inbound.step_handler_port import WorkflowDefinitionRegistryPort

from ip.application.domains.energy.canonical import EnergyEntityType
from ip.application.domains.tms.canonical import TmsEntityType
from ip.engine.domain.stitch import Stitch, StitchStepType
from ip.engine.ports.outbound.stitch_catalog_registry_port import (
    StitchCatalogRegistryPort,
)


def build_default_stitch_definitions() -> tuple[WorkflowDefinition, ...]:
    """Return built-in static DAG WorkflowDefinitions for Energy and TMS verticals."""
    energy_outage_stitch = WorkflowDefinition(
        workflow_id="energy.outage_restoration_stitch",
        version=1,
        default_priority=Priority.REALTIME,
        description=(
            "Enriches AMI outage event context, waits for meter restoration signal, "
            "and emits a Stage-1 operational notification."
        ),
        nodes=(
            NodeDefinition(
                node_key="lookup_meter_replica",
                kind=NodeKind.TASK,
                step_type=StitchStepType.QUERY_REPLICA.value,
                effect_policy=EffectPolicy.PURE,
            ),
            NodeDefinition(
                node_key="wait_restored",
                kind=NodeKind.WAIT_FOR_EVENT,
                parents=("lookup_meter_replica",),
                wait_event=WaitEventSpec(
                    event_key="canonical.meter_restored.normalized",
                    timeout=timedelta(hours=2),
                ),
            ),
            NodeDefinition(
                node_key="notify_grid_ops",
                kind=NodeKind.TASK,
                step_type=StitchStepType.EMIT_NOTIFICATION.value,
                parents=("wait_restored",),
                effect_policy=EffectPolicy.IDEMPOTENT_EFFECT,
            ),
        ),
    )

    energy_erp_sync_stitch = WorkflowDefinition(
        workflow_id="energy.meter_reading_erp_sync_stitch",
        version=1,
        default_priority=Priority.BULK,
        description=(
            "Synchronizes normalized AMI interval meter readings to downstream utility ERP/CIS."
        ),
        nodes=(
            NodeDefinition(
                node_key="lookup_service_point",
                kind=NodeKind.TASK,
                step_type=StitchStepType.QUERY_REPLICA.value,
                effect_policy=EffectPolicy.PURE,
            ),
            NodeDefinition(
                node_key="dispatch_erp_reading",
                kind=NodeKind.TASK,
                step_type=StitchStepType.EXECUTE_HTTP_ACTION.value,
                parents=("lookup_service_point",),
                effect_policy=EffectPolicy.RECONCILABLE_EFFECT,
            ),
        ),
    )

    tms_load_sync_stitch = WorkflowDefinition(
        workflow_id="tms.load_tender_erp_sync_stitch",
        version=1,
        default_priority=Priority.REALTIME,
        description=(
            "Validates carrier replica state for a normalized TMS load and dispatches "
            "a freight invoice action to downstream ERP."
        ),
        nodes=(
            NodeDefinition(
                node_key="lookup_carrier_replica",
                kind=NodeKind.TASK,
                step_type=StitchStepType.QUERY_REPLICA.value,
                effect_policy=EffectPolicy.PURE,
            ),
            NodeDefinition(
                node_key="dispatch_erp_invoice",
                kind=NodeKind.TASK,
                step_type=StitchStepType.EXECUTE_HTTP_ACTION.value,
                parents=("lookup_carrier_replica",),
                effect_policy=EffectPolicy.RECONCILABLE_EFFECT,
            ),
            NodeDefinition(
                node_key="notify_logistics_ops",
                kind=NodeKind.TASK,
                step_type=StitchStepType.EMIT_NOTIFICATION.value,
                parents=("dispatch_erp_invoice",),
                effect_policy=EffectPolicy.IDEMPOTENT_EFFECT,
            ),
        ),
    )

    return (
        energy_outage_stitch,
        energy_erp_sync_stitch,
        tms_load_sync_stitch,
    )


def build_default_stitches() -> tuple[Stitch, ...]:
    """Return built-in wildcard Stitches connecting canonical events to workflows."""
    return (
        Stitch(
            id="stch_default_energy_reading_sync",
            tenant_id="*",
            workflow_id="energy.meter_reading_erp_sync_stitch",
            workflow_version=1,
            canonical_event_type=EnergyEntityType.MDM_METER_READING.value,
            is_trigger=True,
            idempotency_key_field="source_id",
            concurrency_key_field="meter_serial_number",
            is_active=True,
        ),
        Stitch(
            id="stch_default_tms_load_sync",
            tenant_id="*",
            workflow_id="tms.load_tender_erp_sync_stitch",
            workflow_version=1,
            canonical_event_type=TmsEntityType.TMS_LOAD.value,
            is_trigger=True,
            idempotency_key_field="source_id",
            concurrency_key_field="load_reference_number",
            is_active=True,
        ),
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
