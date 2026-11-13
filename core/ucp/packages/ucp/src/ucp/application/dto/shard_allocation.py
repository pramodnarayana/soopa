from dataclasses import dataclass
from enum import StrEnum


class ShardAllocationErrorCode(StrEnum):
    NO_ACTIVE_SHARDS = "NO_ACTIVE_SHARDS"
    SHARD_CAPACITY_EXHAUSTED = "SHARD_CAPACITY_EXHAUSTED"
    APP_NOT_FOUND = "APP_NOT_FOUND"


@dataclass(frozen=True)
class ShardCandidateDTO:
    """Represents an active candidate database shard available for allocation."""

    shard_id: str
    shard_name: str
    current_tenant_count: int
    status: str


@dataclass(frozen=True)
class ShardAllocationProblem:
    """Structured operational problem when shard allocation cannot be fulfilled."""

    code: ShardAllocationErrorCode
    message: str
    app_slug: str
    tenant_id: str
