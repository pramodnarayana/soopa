"""Energy HES historical extraction L4 Stitch workflow and definition."""

from __future__ import annotations

from orchestration.domain.constants import EffectPolicy, NodeKind, Priority
from orchestration.domain.definition import NodeDefinition, WorkflowDefinition

from ip.engine.domain.stitch.enums import StitchStepType
from ip.engine.domain.stitch.stitch import Stitch


def build_hes_historical_extraction_definition() -> WorkflowDefinition:
    """Build the WorkflowDefinition for decomposing MDM historical extract requests."""
    return WorkflowDefinition(
        workflow_id="energy.hes_historical_extraction_stitch",
        version=1,
        default_priority=Priority.BULK,
        description=(
            "Decomposes MDM historical extract requests into atomic daily pull tasks per HES connection."
        ),
        nodes=(
            NodeDefinition(
                node_key="slice_date_range",
                kind=NodeKind.TASK,
                step_type=StitchStepType.SLICE_RANGE.value,
                effect_policy=EffectPolicy.PURE,
            ),
        ),
    )


def build_hes_historical_extraction_stitch() -> Stitch:
    """Build the wildcard Stitch triggering historical extraction on extract command events."""
    return Stitch(
        id="stch_default_hes_historical_extraction",
        tenant_id="*",
        canonical_event_type="command.historical_extract_requests",
        target_workflow_id="energy.hes_historical_extraction_stitch",
        name="Default HES Historical Extraction",
        description="Decomposes MDM historical extract requests into atomic daily pull tasks per HES connection.",
        idempotency_key_field="source_inbound_record_id",
        is_active=False,
    )


__all__ = [
    "build_hes_historical_extraction_definition",
    "build_hes_historical_extraction_stitch",
]
