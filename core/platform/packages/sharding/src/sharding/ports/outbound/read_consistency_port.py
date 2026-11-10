"""Polymorphic CQRS Read Consistency Policy & Writer Bulkhead Ports."""

from __future__ import annotations

from typing import Protocol

from sharding.domain.topology import (
    ReadRouteDecisionDTO,
    ReplicationWatermark,
    ShardEndpointDTO,
)


class ReplicaWatermarkProbePort(Protocol):
    """Port exposing latest observed `ReplicationWatermark` for a Pod's Read Replica pool."""

    def get_cached_watermark(self, shard_id: str) -> ReplicationWatermark | None: ...


class WriterFallbackBulkheadPort(Protocol):
    """Non-blocking bulkhead protecting Primary Writer pools from replica fallback storms."""

    def try_acquire_writer_fallback(self, shard_id: str) -> bool: ...


class ReadConsistencyPolicyPort(Protocol):
    """Polymorphic Strategy Port selecting Reader vs. Writer target pools."""

    def validate_probe_configuration(
        self,
        watermark_probe: ReplicaWatermarkProbePort | None,
    ) -> None: ...

    def select_route(
        self,
        endpoint: ShardEndpointDTO,
        watermark_probe: ReplicaWatermarkProbePort | None,
        fallback_bulkhead: WriterFallbackBulkheadPort,
    ) -> ReadRouteDecisionDTO: ...


__all__ = [
    "ReadConsistencyPolicyPort",
    "ReplicaWatermarkProbePort",
    "WriterFallbackBulkheadPort",
]
