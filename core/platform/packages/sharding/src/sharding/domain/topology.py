"""Pure Domain Topology & Routing Value Objects for Multi-Tenant & Cellular Sharding."""

from __future__ import annotations

from dataclasses import dataclass
from typing import NewType

from sharding.domain.constants import (
    DatabaseShardStatus,
    ReadRouteDisposition,
    ReadTargetRole,
    ShardResolutionFailureReason,
    ShardResolutionStatus,
    ShardRoutingStrategy,
)

# Monotonic 64-bit causal database replication watermark (e.g., PostgreSQL WAL byte offset from 0/0).
ReplicationWatermark = NewType("ReplicationWatermark", int)


@dataclass(frozen=True)
class ShardEndpointDTO:
    """Single-table routing DTO mapped from `ucp.database_shards`."""

    shard_id: str
    shard_name: str
    writer_dsn: str
    reader_dsn: str
    status: DatabaseShardStatus
    routing_strategy: ShardRoutingStrategy


@dataclass(frozen=True)
class VirtualBucketAssignmentDTO:
    """Single-table DTO mapped from `ucp.virtual_bucket_assignments`."""

    assignment_id: str
    app_id: str
    bucket_start: int
    bucket_end: int
    shard_id: str


@dataclass(frozen=True)
class ShardResolutionOutcome:
    """First-class result for Pod resolution without raising exceptions on misses."""

    status: ShardResolutionStatus
    endpoint: ShardEndpointDTO | None
    virtual_bucket: int | None = None
    reason: ShardResolutionFailureReason | None = None


@dataclass(frozen=True)
class ReadRouteDecisionDTO:
    """Deterministic CQRS read routing decision produced by `ReadConsistencyPolicyPort`."""

    target_role: ReadTargetRole
    target_dsn: str
    pool_key: str
    disposition: ReadRouteDisposition = ReadRouteDisposition.REPLICA_SELECTED
    observed_watermark: ReplicationWatermark | None = None


__all__ = [
    "ReadRouteDecisionDTO",
    "ReplicationWatermark",
    "ShardEndpointDTO",
    "ShardResolutionOutcome",
    "VirtualBucketAssignmentDTO",
]
