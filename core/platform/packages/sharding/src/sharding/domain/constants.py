"""Enterprise Sharding & Cellular Topology Constants and State Machine Enums."""

from __future__ import annotations

from enum import StrEnum
from typing import Final

VIRTUAL_BUCKET_RING_SIZE: Final[int] = 4096


class DatabaseShardStatus(StrEnum):
    """Lifecycle and live-cutover state machine for Workload Pods (Database Shards)."""

    ACTIVE = "active"
    REPLICATING = "replicating"
    WRITE_FENCED = "write_fenced"
    INACTIVE = "inactive"


class ShardRoutingStrategy(StrEnum):
    """Deterministic Pod routing topology configured per DatabaseShard / App."""

    TENANT_REGISTRY = "tenant_registry"
    VIRTUAL_BUCKET_RING = "virtual_bucket_ring"


class ReadTargetRole(StrEnum):
    """Physical database engine role targeted by a CQRS query route."""

    READER = "reader"
    WRITER = "writer"


class ShardResolutionStatus(StrEnum):
    """First-class outcome status for shard resolution without exception control flow."""

    RESOLVED = "resolved"
    NOT_FOUND = "not_found"
    WRITE_FENCED = "write_fenced"


class ShardResolutionFailureReason(StrEnum):
    """Strongly-typed failure reasons for `ShardResolutionOutcome` (zero magic strings)."""

    TENANT_UNMAPPED = "tenant_unmapped"
    SHARD_INACTIVE = "shard_inactive"
    BUCKET_UNMAPPED_OR_INACTIVE = "bucket_unmapped_or_inactive"
    CUTOVER_WRITE_FENCE = "shard_undergoing_cutover_write_fence"
    RING_TOPOLOGY_INVALID = "ring_topology_invalid"


class ReadRouteDisposition(StrEnum):
    """Semantic CQRS read-routing disposition replacing boolean `fallback_used` flags."""

    REPLICA_SELECTED = "replica_selected"
    PRIMARY_SELECTED = "primary_selected"
    CAUSAL_WRITER_FALLBACK = "causal_writer_fallback"
    CAUSAL_BULKHEAD_DEGRADED = "causal_bulkhead_degraded"


__all__ = [
    "VIRTUAL_BUCKET_RING_SIZE",
    "DatabaseShardStatus",
    "ReadRouteDisposition",
    "ReadTargetRole",
    "ShardResolutionFailureReason",
    "ShardResolutionStatus",
    "ShardRoutingStrategy",
]
