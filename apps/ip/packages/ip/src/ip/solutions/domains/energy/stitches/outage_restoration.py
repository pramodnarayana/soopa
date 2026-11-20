"""Energy outage restoration L4 Stitch workflow definition."""

from __future__ import annotations

from datetime import timedelta

from orchestration.domain.constants import EffectPolicy, NodeKind, Priority
from orchestration.domain.definition import (
    NodeDefinition,
    WaitEventSpec,
    WorkflowDefinition,
)

from ip.engine.domain.stitch.enums import StitchStepType


def build_outage_restoration_definition() -> WorkflowDefinition:
    """Build the WorkflowDefinition for AMI outage restoration orchestration."""
    return WorkflowDefinition(
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


__all__ = [
    "build_outage_restoration_definition",
]
