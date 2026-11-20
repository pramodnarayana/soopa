"""Outbound Stitch adapters for Layer 4 of the Integration Platform."""

from __future__ import annotations

from ip.engine.adapters.outbound.stitches.durable_workflow_orchestrator_adapter import (
    DurableWorkflowOrchestratorAdapter,
)
from ip.engine.adapters.outbound.stitches.handlers import (
    EgressPublishStepHandler,
    EmitNotificationStepHandler,
    ExecuteHttpActionStepHandler,
    HttpDispatchStepHandler,
    L1PersistStepHandler,
    L2ReplicaStepHandler,
    NormalizerStepHandler,
    QueryReplicaStepHandler,
    SliceRangeStepHandler,
    UiFieldMapperStepHandler,
)
from ip.engine.adapters.outbound.stitches.stitch_adapters import (
    IpStitchCanonicalDispatcherAdapter,
    IpStitchWorkerTickAdapter,
)
from ip.engine.adapters.outbound.stitches.stitch_catalog_registry import (
    InMemoryStitchCatalogRegistry,
)
from ip.engine.ports.outbound.notification_outbox_port import NotificationOutboxPort
from ip.engine.ports.outbound.outbound_delivery_stager_port import (
    OutboundDeliveryStagerPort,
)
from ip.engine.ports.outbound.replica_lookup_port import ReplicaLookupPort

__all__ = [
    "DurableWorkflowOrchestratorAdapter",
    "EgressPublishStepHandler",
    "EmitNotificationStepHandler",
    "ExecuteHttpActionStepHandler",
    "HttpDispatchStepHandler",
    "InMemoryStitchCatalogRegistry",
    "IpStitchCanonicalDispatcherAdapter",
    "IpStitchWorkerTickAdapter",
    "L1PersistStepHandler",
    "L2ReplicaStepHandler",
    "NormalizerStepHandler",
    "NotificationOutboxPort",
    "OutboundDeliveryStagerPort",
    "QueryReplicaStepHandler",
    "ReplicaLookupPort",
    "SliceRangeStepHandler",
    "UiFieldMapperStepHandler",
]
