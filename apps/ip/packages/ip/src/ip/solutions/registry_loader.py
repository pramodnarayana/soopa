"""Default L4 Stitch WorkflowDefinition and Stitch registry loader across all domain bounded contexts."""

from __future__ import annotations

from identity.domain.identity_context import PLATFORM_TENANT_ID
from orchestration.application.services import InMemoryWorkflowDefinitionRegistry
from orchestration.domain.constants import EffectPolicy, NodeKind, Priority
from orchestration.domain.definition import NodeDefinition, WorkflowDefinition
from orchestration.ports.inbound.step_handler_port import WorkflowDefinitionRegistryPort

from ip.engine.domain.stitch.enums import StitchStepType
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


def build_transactional_stitch_definitions() -> tuple[WorkflowDefinition, ...]:
    """Return built-in DAG WorkflowDefinitions for transactional order-to-cash pipelines."""
    return (
        WorkflowDefinition(
            workflow_id="workflow.shopify_orders_to_sap",
            version=1,
            default_priority=Priority.HIGH,
            description="Validates incoming Shopify orders, maps entities via GEM, and dispatches to SAP S/4HANA ERP.",
            nodes=(
                NodeDefinition(
                    node_key="validate_payload",
                    kind=NodeKind.TASK,
                    step_type=StitchStepType.VALIDATE_SCHEMA.value,
                    effect_policy=EffectPolicy.PURE,
                    queue_name="ip-dp-default",
                ),
                NodeDefinition(
                    node_key="normalize_entities",
                    kind=NodeKind.TASK,
                    step_type=StitchStepType.CANONICAL_TRANSFORM.value,
                    parents=("validate_payload",),
                    effect_policy=EffectPolicy.PURE,
                    queue_name="ip-dp-default",
                ),
                NodeDefinition(
                    node_key="gem_crosswalk",
                    kind=NodeKind.TASK,
                    step_type=StitchStepType.GEM_LOOKUP.value,
                    parents=("normalize_entities",),
                    effect_policy=EffectPolicy.PURE,
                    queue_name="ip-dp-default",
                ),
                NodeDefinition(
                    node_key="outbound_http",
                    kind=NodeKind.TASK,
                    step_type=StitchStepType.EXECUTE_HTTP_ACTION.value,
                    parents=("gem_crosswalk",),
                    effect_policy=EffectPolicy.RECONCILABLE_EFFECT,
                    queue_name="ip-dp-outbound",
                ),
            ),
        ),
        WorkflowDefinition(
            workflow_id="workflow.sync_alpha_to_sink",
            version=1,
            default_priority=Priority.HIGH,
            description="Validates canonical alpha records and dispatches payloads to Globex Sink.",
            nodes=(
                NodeDefinition(
                    node_key="validate_payload",
                    kind=NodeKind.TASK,
                    step_type=StitchStepType.VALIDATE_SCHEMA.value,
                    effect_policy=EffectPolicy.PURE,
                    queue_name="ip-dp-default",
                ),
                NodeDefinition(
                    node_key="deliver_globex_sink",
                    kind=NodeKind.TASK,
                    step_type=StitchStepType.EXECUTE_HTTP_ACTION.value,
                    parents=("validate_payload",),
                    effect_policy=EffectPolicy.RECONCILABLE_EFFECT,
                    queue_name="ip-dp-outbound",
                ),
            ),
        ),
    )


def build_transactional_stitches() -> tuple[Stitch, ...]:
    """Return built-in platform-shared Stitches connecting transactional canonical events to workflows."""
    return (
        Stitch(
            id="stch_default_shopify_orders_to_sap",
            tenant_id=PLATFORM_TENANT_ID,
            canonical_event_type="canonical.order.v1",
            target_workflow_id="workflow.shopify_orders_to_sap",
            workflow_id="workflow.shopify_orders_to_sap",
            name="Shopify Orders to SAP S/4HANA",
            description="Validates incoming Shopify orders, maps entities via GEM, and dispatches to SAP S/4HANA ERP.",
            idempotency_key_field="event_id",
            concurrency_key_field="order_id",
            is_active=False,
        ),
        Stitch(
            id="stch_default_sync_alpha_to_sink",
            tenant_id=PLATFORM_TENANT_ID,
            canonical_event_type="canonical.record_alpha.v1",
            target_workflow_id="workflow.sync_alpha_to_sink",
            workflow_id="workflow.sync_alpha_to_sink",
            name="Sync Alpha to Globex Sink",
            description="Validates canonical alpha records and dispatches payloads to Globex Sink.",
            idempotency_key_field="event_id",
            concurrency_key_field="record_id",
            is_active=False,
        ),
    )


def build_default_stitch_definitions() -> tuple[WorkflowDefinition, ...]:
    """Return built-in static DAG WorkflowDefinitions for all verticals and integration patterns."""
    return (
        *build_transactional_stitch_definitions(),
        *build_energy_stitch_definitions(),
        *build_tms_stitch_definitions(),
    )


def build_default_stitches() -> tuple[Stitch, ...]:
    """Return built-in platform-shared Stitches connecting canonical events to workflows."""
    return (
        *build_transactional_stitches(),
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
    "build_transactional_stitch_definitions",
    "build_transactional_stitches",
    "create_default_workflow_definition_registry",
    "register_default_stitch_definitions",
    "register_default_stitches",
]
