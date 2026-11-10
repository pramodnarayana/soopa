"""
Deterministic 4,096-Bucket Cellular Consistent-Hash Ring.

Routes million-user Consumer / B2B2C workloads to Database Pods in O(log M)
in-memory time with zero Global DB lookups per subject, while supporting
live Pod splits and write-fenced online cutovers.
"""

from __future__ import annotations

import hashlib
from bisect import bisect_right
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from database.constants import (
    VIRTUAL_BUCKET_RING_SIZE,
    DatabaseShardStatus,
    ShardResolutionStatus,
    ShardRoutingStrategy,
)


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
    reason: str | None = None


def compute_virtual_bucket(
    subject_key: str,
    ring_size: int = VIRTUAL_BUCKET_RING_SIZE,
) -> int:
    """Compute a deterministic, cross-platform virtual bucket in `[0, ring_size)`."""
    normalized = subject_key.strip()
    if not normalized:
        raise ValueError("subject_key must be non-empty")
    if ring_size <= 0:
        raise ValueError("ring_size must be strictly positive")

    digest = hashlib.blake2b(normalized.encode("utf-8"), digest_size=8).digest()
    uint64_hash = int.from_bytes(digest, byteorder="big", signed=False)
    return uint64_hash % ring_size


class VirtualBucketRing:
    """Immutable binary-searchable cellular ring covering `[0, ring_size - 1]`."""

    def __init__(
        self,
        starts: tuple[int, ...],
        ends: tuple[int, ...],
        endpoints: tuple[ShardEndpointDTO, ...],
        ring_size: int = VIRTUAL_BUCKET_RING_SIZE,
    ) -> None:
        self._starts = starts
        self._ends = ends
        self._endpoints = endpoints
        self._ring_size = ring_size

    @classmethod
    def from_assignments(
        cls,
        assignments: Sequence[VirtualBucketAssignmentDTO],
        shards_by_id: Mapping[str, ShardEndpointDTO],
        ring_size: int = VIRTUAL_BUCKET_RING_SIZE,
    ) -> VirtualBucketRing:
        """Validate full contiguous `[0..ring_size-1]` coverage and compile the ring."""
        if not assignments:
            raise ValueError(f"VirtualBucketRing must cover 0..{ring_size - 1}, got empty list")

        ordered = sorted(assignments, key=lambda item: item.bucket_start)
        expected_start = 0
        starts: list[int] = []
        ends: list[int] = []
        endpoints: list[ShardEndpointDTO] = []

        for item in ordered:
            if item.bucket_start != expected_start or item.bucket_end < item.bucket_start:
                raise ValueError(
                    f"VirtualBucketRing must cover 0..{ring_size - 1} contiguously without gaps or overlaps"
                )
            endpoint = shards_by_id.get(item.shard_id)
            if endpoint is None:
                raise ValueError(f"Missing ShardEndpointDTO for shard_id '{item.shard_id}'")
            starts.append(item.bucket_start)
            ends.append(item.bucket_end)
            endpoints.append(endpoint)
            expected_start = item.bucket_end + 1

        if expected_start != ring_size:
            raise ValueError(
                f"VirtualBucketRing must cover 0..{ring_size - 1}, ended at {expected_start - 1}"
            )

        return cls(
            starts=tuple(starts),
            ends=tuple(ends),
            endpoints=tuple(endpoints),
            ring_size=ring_size,
        )

    def _lookup_endpoint(self, bucket: int) -> ShardEndpointDTO | None:
        if bucket < 0 or bucket >= self._ring_size:
            return None
        idx = bisect_right(self._starts, bucket) - 1
        if idx < 0 or bucket > self._ends[idx]:
            return None
        return self._endpoints[idx]

    def resolve_bucket(self, bucket: int) -> ShardResolutionOutcome:
        """Resolve a virtual bucket for read operations (permits `WRITE_FENCED` shards)."""
        endpoint = self._lookup_endpoint(bucket)
        if endpoint is None or endpoint.status == DatabaseShardStatus.INACTIVE:
            return ShardResolutionOutcome(
                status=ShardResolutionStatus.NOT_FOUND,
                endpoint=None,
                virtual_bucket=bucket,
                reason="bucket_unmapped_or_inactive",
            )
        return ShardResolutionOutcome(
            status=ShardResolutionStatus.RESOLVED,
            endpoint=endpoint,
            virtual_bucket=bucket,
        )

    def resolve_bucket_for_write(self, bucket: int) -> ShardResolutionOutcome:
        """Resolve a virtual bucket for write operations, enforcing cutover write-fences."""
        outcome = self.resolve_bucket(bucket)
        if outcome.endpoint is not None and (
            outcome.endpoint.status == DatabaseShardStatus.WRITE_FENCED
        ):
            return ShardResolutionOutcome(
                status=ShardResolutionStatus.WRITE_FENCED,
                endpoint=outcome.endpoint,
                virtual_bucket=bucket,
                reason="shard_undergoing_cutover_write_fence",
            )
        return outcome

    def resolve_subject(self, subject_key: str) -> ShardResolutionOutcome:
        """Hash `subject_key` and resolve its target read Pod."""
        bucket = compute_virtual_bucket(subject_key, ring_size=self._ring_size)
        return self.resolve_bucket(bucket)

    def resolve_subject_for_write(self, subject_key: str) -> ShardResolutionOutcome:
        """Hash `subject_key` and resolve its target write Pod with fence protection."""
        bucket = compute_virtual_bucket(subject_key, ring_size=self._ring_size)
        return self.resolve_bucket_for_write(bucket)


__all__ = [
    "ShardEndpointDTO",
    "ShardResolutionOutcome",
    "VirtualBucketAssignmentDTO",
    "VirtualBucketRing",
    "compute_virtual_bucket",
]
