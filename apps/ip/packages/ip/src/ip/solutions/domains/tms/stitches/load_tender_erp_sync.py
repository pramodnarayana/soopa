"""TMS load tender ERP sync L4 Stitch workflow and definition."""

from __future__ import annotations

from identity.domain.identity_context import PLATFORM_TENANT_ID
from orchestration.domain.constants import EffectPolicy, NodeKind, Priority
from orchestration.domain.definition import NodeDefinition, WorkflowDefinition

from ip.engine.domain.stitch.enums import StitchStepType
from ip.engine.domain.stitch.stitch import Stitch
from ip.solutions.domains.tms.canonical import TmsEntityType


def build_load_tender_erp_sync_definition() -> WorkflowDefinition:
    """Build the WorkflowDefinition for TMS load tender ERP synchronization."""
    return WorkflowDefinition(
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


def build_load_tender_erp_sync_stitch() -> Stitch:
    """Build the platform-shared Stitch triggering the ERP sync workflow on TMS loads."""
    return Stitch(
        id="stch_default_tms_load_sync",
        tenant_id=PLATFORM_TENANT_ID,
        canonical_event_type=TmsEntityType.TMS_LOAD.value,
        target_workflow_id="tms.load_tender_erp_sync_stitch",
        name="TMS Load Tender ERP Sync",
        description="Validates carrier replica state for a normalized TMS load and dispatches a freight invoice action to downstream ERP.",
        idempotency_key_field="event_id",
        concurrency_key_field="load_reference_number",
        is_active=False,
    )


__all__ = [
    "build_load_tender_erp_sync_definition",
    "build_load_tender_erp_sync_stitch",
]
