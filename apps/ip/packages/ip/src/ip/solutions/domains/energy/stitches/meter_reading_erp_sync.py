"""Energy meter reading ERP sync L4 Stitch workflow and definition."""

from __future__ import annotations

from orchestration.domain.constants import EffectPolicy, NodeKind, Priority
from orchestration.domain.definition import (
    ConcurrencyPolicy,
    NodeDefinition,
    WorkflowDefinition,
)

from ip.engine.domain.stitch.enums import StitchStepType
from ip.engine.domain.stitch.stitch import Stitch
from ip.solutions.domains.energy.canonical import EnergyEntityType


def build_meter_reading_erp_sync_definition() -> WorkflowDefinition:
    """Build the WorkflowDefinition for synchronizing normalized meter readings to ERP/CIS."""
    return WorkflowDefinition(
        workflow_id="energy.meter_reading_erp_sync_stitch",
        version=1,
        default_priority=Priority.BULK,
        description=(
            "Synchronizes normalized AMI interval meter readings to downstream utility ERP/CIS."
        ),
        workflow_concurrency=ConcurrencyPolicy(
            strategy_id="meter_serial_fifo",
            key_template="{input.meter_serial_number}",
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


def build_meter_reading_erp_sync_stitch() -> Stitch:
    """Build the wildcard Stitch triggering the ERP sync workflow on MDM meter readings."""
    return Stitch(
        id="stch_default_energy_reading_sync",
        tenant_id="*",
        canonical_event_type=EnergyEntityType.MDM_METER_READING.value,
        target_workflow_id="energy.meter_reading_erp_sync_stitch",
        name="AMI Energy Meter Reading ERP Sync",
        description="Synchronizes normalized AMI interval meter readings to downstream utility ERP/CIS.",
        idempotency_key_field="event_id",
        concurrency_key_field="meter_serial_number",
        is_active=False,
    )


__all__ = [
    "build_meter_reading_erp_sync_definition",
    "build_meter_reading_erp_sync_stitch",
]
