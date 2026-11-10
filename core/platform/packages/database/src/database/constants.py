from enum import StrEnum
from typing import Final

VIRTUAL_BUCKET_RING_SIZE: Final[int] = 4096
MAX_PG_IDENTIFIER_LENGTH: Final[int] = 63


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


class PartitionCadence(StrEnum):
    """Time-range granularity for PostgreSQL declarative partitioning."""

    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class PartitionDetachStatus(StrEnum):
    """Outcome status for non-blocking PostgreSQL partition detach operations."""

    DETACHED = "detached"
    NOT_FOUND = "not_found"
