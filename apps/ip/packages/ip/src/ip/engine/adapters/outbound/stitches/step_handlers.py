"""Deprecated shim for stitch step handlers.

This module has been decomposed into individual handler modules under
`ip.engine.adapters.outbound.stitches.handlers`, ports under `ip.engine.ports.outbound`,
and database adapters under `ip.engine.adapters.outbound.database.data_plane.tenant_lookup_adapters`.
"""

from __future__ import annotations

from ip.engine.adapters.outbound.database.data_plane.tenant_lookup_adapters import (
    TenantAwareNotificationOutboxAdapter,
    TenantAwareOutboundRecordLookupAdapter,
    TenantAwareReplicaLookupAdapter,
)
from ip.engine.adapters.outbound.stitches.handlers import (
    # Deprecated ChildWorkflowFanOutStepHandler removed: violates SRP.
    # Fanout is handled via queue-backed task dispatching.
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
from ip.engine.ports.outbound.notification_outbox_port import NotificationOutboxPort
from ip.engine.ports.outbound.outbound_delivery_stager_port import (
    OutboundDeliveryStagerPort,
)
from ip.engine.ports.outbound.outbound_record_lookup_port import (
    OutboundRecordLookupPort,
)
from ip.engine.ports.outbound.replica_lookup_port import ReplicaLookupPort

__all__ = [
    "EgressPublishStepHandler",
    "EmitNotificationStepHandler",
    "ExecuteHttpActionStepHandler",
    "HttpDispatchStepHandler",
    "L1PersistStepHandler",
    "L2ReplicaStepHandler",
    "NormalizerStepHandler",
    "NotificationOutboxPort",
    "OutboundDeliveryStagerPort",
    "OutboundRecordLookupPort",
    "QueryReplicaStepHandler",
    "ReplicaLookupPort",
    "SliceRangeStepHandler",
    "TenantAwareNotificationOutboxAdapter",
    "TenantAwareOutboundRecordLookupAdapter",
    "TenantAwareReplicaLookupAdapter",
    "UiFieldMapperStepHandler",
]
