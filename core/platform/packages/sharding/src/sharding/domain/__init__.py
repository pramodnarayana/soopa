"""Domain layer for Multi-Tenant & Cellular Sharding."""

from sharding.domain.cellular_ring import VirtualBucketRing, compute_virtual_bucket
from sharding.domain.constants import (
    VIRTUAL_BUCKET_RING_SIZE,
    DatabaseShardStatus,
    ReadRouteDisposition,
    ReadTargetRole,
    ShardResolutionFailureReason,
    ShardResolutionStatus,
    ShardRoutingStrategy,
)
from sharding.domain.exceptions import (
    ShardingInfrastructureError,
    TenantNotFoundError,
)
from sharding.domain.topology import (
    ReadRouteDecisionDTO,
    ReplicationWatermark,
    ShardEndpointDTO,
    ShardResolutionOutcome,
    VirtualBucketAssignmentDTO,
)

__all__ = [
    "VIRTUAL_BUCKET_RING_SIZE",
    "DatabaseShardStatus",
    "ReadRouteDecisionDTO",
    "ReadRouteDisposition",
    "ReadTargetRole",
    "ReplicationWatermark",
    "ShardEndpointDTO",
    "ShardResolutionFailureReason",
    "ShardResolutionOutcome",
    "ShardResolutionStatus",
    "ShardRoutingStrategy",
    "ShardingInfrastructureError",
    "TenantNotFoundError",
    "VirtualBucketAssignmentDTO",
    "VirtualBucketRing",
    "compute_virtual_bucket",
]
