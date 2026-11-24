"""Energy HES historical extraction L4 Stitch workflows and definitions.

Authored by the Energy Domain Solution Engineer (Pure Python Code):
- Track 0 (Outbound): Slices MDM date range and fans out parallel commands to Itron, Landis+Gyr, and Siemens HES.
- Track 1 (Inbound): Three separate, autonomous streaming pipelines (Itron, Landis+Gyr, Siemens).
- Zero consolidation: Each stream publishes to Kafka immediately as it arrives.
- Zero GEM: Pure time-series interval streaming directly to Kafka.
"""

from __future__ import annotations

from orchestration.domain.constants import EffectPolicy, NodeKind, Priority
from orchestration.domain.definition import NodeDefinition, WorkflowDefinition

from ip.engine.domain.stitch.stitch import Stitch

_ENTERPRISE_BOUNDARY = "Enterprise Core (MDM / Kafka)"
_FIELD_BOUNDARY = "Field Infrastructure (HES)"


def build_hes_historical_extraction_definition() -> WorkflowDefinition:
    """Build the unified round-trip WorkflowDefinition across Enterprise and Field boundaries."""
    return WorkflowDefinition(
        workflow_id="energy.hes_historical_extraction_stitch",
        version=1,
        default_priority=Priority.BULK,
        description=(
            "End-to-end multi-HES historical extract journey: slices date range, fans out parallel "
            "commands to Itron, Landis+Gyr, and Siemens HES, and streams each vendor's batch intervals "
            "directly to Kafka independently as soon as each callback arrives (zero consolidation)."
        ),
        nodes=(
            # ── TRACK 0: OUTBOUND REQUEST & MULTI-HES FANOUT (MDM -> HES) ──
            NodeDefinition(
                node_key="request_received",
                kind=NodeKind.TASK,
                step_type="trigger.ingress",
                boundary=_ENTERPRISE_BOUNDARY,
                track=0,
                effect_policy=EffectPolicy.PURE,
            ),
            NodeDefinition(
                node_key="slice_date_range",
                kind=NodeKind.TASK,
                step_type="energy.slice_daily_chunks",
                parents=("request_received",),
                boundary=_ENTERPRISE_BOUNDARY,
                track=0,
                effect_policy=EffectPolicy.PURE,
            ),
            NodeDefinition(
                node_key="fanout_hes_partitions",
                kind=NodeKind.TASK,
                step_type="energy.fanout_by_connection",
                parents=("slice_date_range",),
                boundary=_ENTERPRISE_BOUNDARY,
                track=0,
                effect_policy=EffectPolicy.PURE,
            ),
            # Parallel Fanout Dispatches by Vendor
            NodeDefinition(
                node_key="dispatch_itron_hes",
                kind=NodeKind.TASK,
                step_type="http.post_extract",
                parents=("fanout_hes_partitions",),
                boundary=_FIELD_BOUNDARY,
                track=0,
                effect_policy=EffectPolicy.RECONCILABLE_EFFECT,
            ),
            NodeDefinition(
                node_key="dispatch_landis_gyr_hes",
                kind=NodeKind.TASK,
                step_type="http.post_extract",
                parents=("fanout_hes_partitions",),
                boundary=_FIELD_BOUNDARY,
                track=0,
                effect_policy=EffectPolicy.RECONCILABLE_EFFECT,
            ),
            NodeDefinition(
                node_key="dispatch_siemens_hes",
                kind=NodeKind.TASK,
                step_type="http.post_extract",
                parents=("fanout_hes_partitions",),
                boundary=_FIELD_BOUNDARY,
                track=0,
                effect_policy=EffectPolicy.RECONCILABLE_EFFECT,
            ),
            # ── TRACK 1: INBOUND STREAM 1 (ITRON - SEND AS IT ARRIVES) ──
            NodeDefinition(
                node_key="itron_batch_received",
                kind=NodeKind.TASK,
                step_type="trigger.ingress",
                parents=("dispatch_itron_hes",),
                boundary=_FIELD_BOUNDARY,
                track=1,
                effect_policy=EffectPolicy.PURE,
            ),
            NodeDefinition(
                node_key="decompress_and_parse_itron",
                kind=NodeKind.TASK,
                step_type="itron.parse_openway_batch",
                parents=("itron_batch_received",),
                boundary=_ENTERPRISE_BOUNDARY,
                track=1,
                effect_policy=EffectPolicy.PURE,
            ),
            NodeDefinition(
                node_key="normalize_itron_intervals",
                kind=NodeKind.TASK,
                step_type="itron.normalize_intervals",
                parents=("decompress_and_parse_itron",),
                boundary=_ENTERPRISE_BOUNDARY,
                track=1,
                effect_policy=EffectPolicy.PURE,
            ),
            NodeDefinition(
                node_key="publish_itron_to_kafka",
                kind=NodeKind.TASK,
                step_type="kafka.publish_intervals",
                parents=("normalize_itron_intervals",),
                boundary=_ENTERPRISE_BOUNDARY,
                track=1,
                effect_policy=EffectPolicy.IDEMPOTENT_EFFECT,
            ),
            # ── TRACK 1: INBOUND STREAM 2 (LANDIS+GYR - SEND AS IT ARRIVES) ──
            NodeDefinition(
                node_key="landis_batch_received",
                kind=NodeKind.TASK,
                step_type="trigger.ingress",
                parents=("dispatch_landis_gyr_hes",),
                boundary=_FIELD_BOUNDARY,
                track=1,
                effect_policy=EffectPolicy.PURE,
            ),
            NodeDefinition(
                node_key="decompress_and_parse_landis",
                kind=NodeKind.TASK,
                step_type="landis.parse_cim_batch",
                parents=("landis_batch_received",),
                boundary=_ENTERPRISE_BOUNDARY,
                track=1,
                effect_policy=EffectPolicy.PURE,
            ),
            NodeDefinition(
                node_key="normalize_landis_intervals",
                kind=NodeKind.TASK,
                step_type="landis.normalize_intervals",
                parents=("decompress_and_parse_landis",),
                boundary=_ENTERPRISE_BOUNDARY,
                track=1,
                effect_policy=EffectPolicy.PURE,
            ),
            NodeDefinition(
                node_key="publish_landis_to_kafka",
                kind=NodeKind.TASK,
                step_type="kafka.publish_intervals",
                parents=("normalize_landis_intervals",),
                boundary=_ENTERPRISE_BOUNDARY,
                track=1,
                effect_policy=EffectPolicy.IDEMPOTENT_EFFECT,
            ),
            # ── TRACK 1: INBOUND STREAM 3 (SIEMENS - SEND AS IT ARRIVES) ──
            NodeDefinition(
                node_key="siemens_batch_received",
                kind=NodeKind.TASK,
                step_type="trigger.ingress",
                parents=("dispatch_siemens_hes",),
                boundary=_FIELD_BOUNDARY,
                track=1,
                effect_policy=EffectPolicy.PURE,
            ),
            NodeDefinition(
                node_key="decompress_and_parse_siemens",
                kind=NodeKind.TASK,
                step_type="siemens.parse_energyip_batch",
                parents=("siemens_batch_received",),
                boundary=_ENTERPRISE_BOUNDARY,
                track=1,
                effect_policy=EffectPolicy.PURE,
            ),
            NodeDefinition(
                node_key="normalize_siemens_intervals",
                kind=NodeKind.TASK,
                step_type="siemens.normalize_intervals",
                parents=("decompress_and_parse_siemens",),
                boundary=_ENTERPRISE_BOUNDARY,
                track=1,
                effect_policy=EffectPolicy.PURE,
            ),
            NodeDefinition(
                node_key="publish_siemens_to_kafka",
                kind=NodeKind.TASK,
                step_type="kafka.publish_intervals",
                parents=("normalize_siemens_intervals",),
                boundary=_ENTERPRISE_BOUNDARY,
                track=1,
                effect_policy=EffectPolicy.IDEMPOTENT_EFFECT,
            ),
        ),
    )


def build_hes_historical_extraction_stitch() -> Stitch:
    """Build the unified Stitch triggering historical extraction on extract command events."""
    return Stitch(
        id="stch_hes_historical_extraction",
        tenant_id="*",
        canonical_event_type="command.historical_extract_requests",
        target_workflow_id="energy.hes_historical_extraction_stitch",
        name="HES Historical Interval Extraction",
        description="End-to-end multi-HES historical extract slicing, fanout, and independent streaming to Kafka as data arrives.",
        idempotency_key_field="source_inbound_record_id",
        is_active=False,
        correlation_key_field="callback_correlation_id",
    )


def build_hes_historical_dispatch_definition() -> WorkflowDefinition:
    """Build the Outbound Dispatch WorkflowDefinition (Track 0)."""
    return WorkflowDefinition(
        workflow_id="energy.hes_historical_dispatch_stitch",
        version=1,
        default_priority=Priority.BULK,
        description="Slices MDM historical extract requests and fans out parallel commands to Itron, Landis+Gyr, and Siemens HES.",
        nodes=(
            NodeDefinition(
                node_key="request_received",
                kind=NodeKind.TASK,
                step_type="trigger.ingress",
                boundary=_ENTERPRISE_BOUNDARY,
                track=0,
                effect_policy=EffectPolicy.PURE,
            ),
            NodeDefinition(
                node_key="slice_date_range",
                kind=NodeKind.TASK,
                step_type="energy.slice_daily_chunks",
                parents=("request_received",),
                boundary=_ENTERPRISE_BOUNDARY,
                track=0,
                effect_policy=EffectPolicy.PURE,
            ),
            NodeDefinition(
                node_key="fanout_hes_partitions",
                kind=NodeKind.TASK,
                step_type="energy.fanout_by_connection",
                parents=("slice_date_range",),
                boundary=_ENTERPRISE_BOUNDARY,
                track=0,
                effect_policy=EffectPolicy.PURE,
            ),
            NodeDefinition(
                node_key="dispatch_itron_hes",
                kind=NodeKind.TASK,
                step_type="http.post_extract",
                parents=("fanout_hes_partitions",),
                boundary=_FIELD_BOUNDARY,
                track=0,
                effect_policy=EffectPolicy.RECONCILABLE_EFFECT,
            ),
            NodeDefinition(
                node_key="dispatch_landis_gyr_hes",
                kind=NodeKind.TASK,
                step_type="http.post_extract",
                parents=("fanout_hes_partitions",),
                boundary=_FIELD_BOUNDARY,
                track=0,
                effect_policy=EffectPolicy.RECONCILABLE_EFFECT,
            ),
            NodeDefinition(
                node_key="dispatch_siemens_hes",
                kind=NodeKind.TASK,
                step_type="http.post_extract",
                parents=("fanout_hes_partitions",),
                boundary=_FIELD_BOUNDARY,
                track=0,
                effect_policy=EffectPolicy.RECONCILABLE_EFFECT,
            ),
        ),
    )


def build_hes_historical_dispatch_stitch() -> Stitch:
    """Build the Outbound Dispatch Stitch."""
    return Stitch(
        id="stch_hes_historical_dispatch",
        tenant_id="*",
        canonical_event_type="command.historical_extract_requests",
        target_workflow_id="energy.hes_historical_dispatch_stitch",
        name="HES Historical Extract Dispatch",
        description="Outbound pipeline: slices date range and fans out extract requests to HES endpoints.",
        idempotency_key_field="source_inbound_record_id",
        is_active=False,
        correlation_key_field="callback_correlation_id",
    )


def build_itron_batch_ingestion_definition() -> WorkflowDefinition:
    """Build the Itron Inbound Ingestion WorkflowDefinition (Send As It Arrives)."""
    return WorkflowDefinition(
        workflow_id="energy.itron_batch_ingestion_stitch",
        version=1,
        default_priority=Priority.BULK,
        description="Itron streaming pipeline: parses OpenWay batch, normalizes intervals, and publishes directly to Kafka as it arrives.",
        nodes=(
            NodeDefinition(
                node_key="itron_batch_received",
                kind=NodeKind.TASK,
                step_type="trigger.ingress",
                boundary=_FIELD_BOUNDARY,
                track=1,
                effect_policy=EffectPolicy.PURE,
            ),
            NodeDefinition(
                node_key="decompress_and_parse_itron",
                kind=NodeKind.TASK,
                step_type="itron.parse_openway_batch",
                parents=("itron_batch_received",),
                boundary=_ENTERPRISE_BOUNDARY,
                track=1,
                effect_policy=EffectPolicy.PURE,
            ),
            NodeDefinition(
                node_key="normalize_itron_intervals",
                kind=NodeKind.TASK,
                step_type="itron.normalize_intervals",
                parents=("decompress_and_parse_itron",),
                boundary=_ENTERPRISE_BOUNDARY,
                track=1,
                effect_policy=EffectPolicy.PURE,
            ),
            NodeDefinition(
                node_key="publish_itron_to_kafka",
                kind=NodeKind.TASK,
                step_type="kafka.publish_intervals",
                parents=("normalize_itron_intervals",),
                boundary=_ENTERPRISE_BOUNDARY,
                track=1,
                effect_policy=EffectPolicy.IDEMPOTENT_EFFECT,
            ),
        ),
    )


def build_itron_batch_ingestion_stitch() -> Stitch:
    """Build the Itron Inbound Ingestion Stitch."""
    return Stitch(
        id="stch_itron_batch_ingestion",
        tenant_id="*",
        canonical_event_type="hes.itron.batch_push.received",
        target_workflow_id="energy.itron_batch_ingestion_stitch",
        name="Itron Batch Interval Streaming",
        description="Itron stream: validates, parses, normalizes, and publishes directly to Kafka as it arrives.",
        idempotency_key_field="batch_push_id",
        is_active=False,
        correlation_key_field="callback_correlation_id",
    )


def build_landis_batch_ingestion_definition() -> WorkflowDefinition:
    """Build the Landis+Gyr Inbound Ingestion WorkflowDefinition (Send As It Arrives)."""
    return WorkflowDefinition(
        workflow_id="energy.landis_batch_ingestion_stitch",
        version=1,
        default_priority=Priority.BULK,
        description="Landis+Gyr streaming pipeline: parses CIM batch, normalizes intervals, and publishes directly to Kafka as it arrives.",
        nodes=(
            NodeDefinition(
                node_key="landis_batch_received",
                kind=NodeKind.TASK,
                step_type="trigger.ingress",
                boundary=_FIELD_BOUNDARY,
                track=1,
                effect_policy=EffectPolicy.PURE,
            ),
            NodeDefinition(
                node_key="decompress_and_parse_landis",
                kind=NodeKind.TASK,
                step_type="landis.parse_cim_batch",
                parents=("landis_batch_received",),
                boundary=_ENTERPRISE_BOUNDARY,
                track=1,
                effect_policy=EffectPolicy.PURE,
            ),
            NodeDefinition(
                node_key="normalize_landis_intervals",
                kind=NodeKind.TASK,
                step_type="landis.normalize_intervals",
                parents=("decompress_and_parse_landis",),
                boundary=_ENTERPRISE_BOUNDARY,
                track=1,
                effect_policy=EffectPolicy.PURE,
            ),
            NodeDefinition(
                node_key="publish_landis_to_kafka",
                kind=NodeKind.TASK,
                step_type="kafka.publish_intervals",
                parents=("normalize_landis_intervals",),
                boundary=_ENTERPRISE_BOUNDARY,
                track=1,
                effect_policy=EffectPolicy.IDEMPOTENT_EFFECT,
            ),
        ),
    )


def build_landis_batch_ingestion_stitch() -> Stitch:
    """Build the Landis+Gyr Inbound Ingestion Stitch."""
    return Stitch(
        id="stch_landis_batch_ingestion",
        tenant_id="*",
        canonical_event_type="hes.landis.batch_push.received",
        target_workflow_id="energy.landis_batch_ingestion_stitch",
        name="Landis+Gyr Batch Interval Streaming",
        description="Landis+Gyr stream: validates, parses, normalizes, and publishes directly to Kafka as it arrives.",
        idempotency_key_field="batch_push_id",
        is_active=False,
        correlation_key_field="callback_correlation_id",
    )


def build_siemens_batch_ingestion_definition() -> WorkflowDefinition:
    """Build the Siemens Inbound Ingestion WorkflowDefinition (Send As It Arrives)."""
    return WorkflowDefinition(
        workflow_id="energy.siemens_batch_ingestion_stitch",
        version=1,
        default_priority=Priority.BULK,
        description="Siemens streaming pipeline: parses EnergyIP batch, normalizes intervals, and publishes directly to Kafka as it arrives.",
        nodes=(
            NodeDefinition(
                node_key="siemens_batch_received",
                kind=NodeKind.TASK,
                step_type="trigger.ingress",
                boundary=_FIELD_BOUNDARY,
                track=1,
                effect_policy=EffectPolicy.PURE,
            ),
            NodeDefinition(
                node_key="decompress_and_parse_siemens",
                kind=NodeKind.TASK,
                step_type="siemens.parse_energyip_batch",
                parents=("siemens_batch_received",),
                boundary=_ENTERPRISE_BOUNDARY,
                track=1,
                effect_policy=EffectPolicy.PURE,
            ),
            NodeDefinition(
                node_key="normalize_siemens_intervals",
                kind=NodeKind.TASK,
                step_type="siemens.normalize_intervals",
                parents=("decompress_and_parse_siemens",),
                boundary=_ENTERPRISE_BOUNDARY,
                track=1,
                effect_policy=EffectPolicy.PURE,
            ),
            NodeDefinition(
                node_key="publish_siemens_to_kafka",
                kind=NodeKind.TASK,
                step_type="kafka.publish_intervals",
                parents=("normalize_siemens_intervals",),
                boundary=_ENTERPRISE_BOUNDARY,
                track=1,
                effect_policy=EffectPolicy.IDEMPOTENT_EFFECT,
            ),
        ),
    )


def build_siemens_batch_ingestion_stitch() -> Stitch:
    """Build the Siemens Inbound Ingestion Stitch."""
    return Stitch(
        id="stch_siemens_batch_ingestion",
        tenant_id="*",
        canonical_event_type="hes.siemens.batch_push.received",
        target_workflow_id="energy.siemens_batch_ingestion_stitch",
        name="Siemens Batch Interval Streaming",
        description="Siemens stream: validates, parses, normalizes, and publishes directly to Kafka as it arrives.",
        idempotency_key_field="batch_push_id",
        is_active=False,
        correlation_key_field="callback_correlation_id",
    )


__all__ = [
    "build_hes_historical_dispatch_definition",
    "build_hes_historical_dispatch_stitch",
    "build_hes_historical_extraction_definition",
    "build_hes_historical_extraction_stitch",
    "build_itron_batch_ingestion_definition",
    "build_itron_batch_ingestion_stitch",
    "build_landis_batch_ingestion_definition",
    "build_landis_batch_ingestion_stitch",
    "build_siemens_batch_ingestion_definition",
    "build_siemens_batch_ingestion_stitch",
]
