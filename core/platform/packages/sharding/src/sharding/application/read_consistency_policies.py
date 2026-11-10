"""
Polymorphic CQRS Read Consistency Policies & Metastable Writer Bulkheads.

Replaces boolean control flags (`require_primary=True`) with strategy polymorphism
and causal `ReplicationWatermark` comparison, gated by a per-shard non-blocking
token-bucket bulkhead so Read Replica lag or outages never crush Primary Writers.
"""

from __future__ import annotations

import time
from collections.abc import Callable

import structlog

from sharding.domain.constants import ReadRouteDisposition, ReadTargetRole
from sharding.domain.topology import (
    ReadRouteDecisionDTO,
    ReplicationWatermark,
    ShardEndpointDTO,
)
from sharding.ports.outbound.read_consistency_port import (
    ReadConsistencyPolicyPort,
    ReplicaWatermarkProbePort,
    WriterFallbackBulkheadPort,
)

logger = structlog.get_logger(__name__)


class InMemoryReplicaWatermarkStore(ReplicaWatermarkProbePort):
    """Monotonic in-memory store tracking observed replica replay watermarks per Pod."""

    def __init__(self) -> None:
        self._watermarks: dict[str, ReplicationWatermark] = {}

    def record_watermark(self, shard_id: str, watermark: ReplicationWatermark) -> None:
        current = self._watermarks.get(shard_id)
        if current is None or watermark > current:
            self._watermarks[shard_id] = watermark
            logger.debug(
                "replica_watermark_recorded",
                shard_id=shard_id,
                watermark=int(watermark),
            )
            return
        logger.debug(
            "replica_watermark_update_skipped_monotonic",
            shard_id=shard_id,
            candidate_watermark=int(watermark),
            current_watermark=int(current),
        )

    def get_cached_watermark(self, shard_id: str) -> ReplicationWatermark | None:
        return self._watermarks.get(shard_id)


class TokenBucketWriterFallbackBulkhead(WriterFallbackBulkheadPort):
    """Per-shard token bucket capping RYOW fallback traffic sent to the Primary Writer."""

    def __init__(
        self,
        capacity: int = 25,
        refill_per_second: float = 10.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be strictly positive")
        if refill_per_second <= 0.0:
            raise ValueError("refill_per_second must be strictly positive")
        self._capacity = float(capacity)
        self._refill_per_second = refill_per_second
        self._clock = clock
        self._buckets: dict[str, tuple[float, float]] = {}

    def try_acquire_writer_fallback(self, shard_id: str) -> bool:
        now = self._clock()
        tokens, last_ts = self._buckets.get(shard_id, (self._capacity, now))
        elapsed = max(0.0, now - last_ts)
        replenished = min(self._capacity, tokens + elapsed * self._refill_per_second)
        if replenished >= 1.0:
            self._buckets[shard_id] = (replenished - 1.0, now)
            return True

        self._buckets[shard_id] = (replenished, now)
        logger.error(
            "writer_fallback_bulkhead_throttled",
            shard_id=shard_id,
            available_tokens=replenished,
        )
        return False


class EventualReplicaPolicy(ReadConsistencyPolicyPort):
    """High-throughput default strategy routing queries to the Pod's Read Replica pool."""

    def validate_probe_configuration(
        self,
        watermark_probe: ReplicaWatermarkProbePort | None,
    ) -> None:
        _ = watermark_probe

    def select_route(
        self,
        endpoint: ShardEndpointDTO,
        watermark_probe: ReplicaWatermarkProbePort | None,
        fallback_bulkhead: WriterFallbackBulkheadPort,
    ) -> ReadRouteDecisionDTO:
        _ = fallback_bulkhead
        observed = (
            watermark_probe.get_cached_watermark(endpoint.shard_id)
            if watermark_probe is not None
            else None
        )
        return ReadRouteDecisionDTO(
            target_role=ReadTargetRole.READER,
            target_dsn=endpoint.reader_dsn,
            pool_key=f"{endpoint.shard_id}:{ReadTargetRole.READER.value}",
            disposition=ReadRouteDisposition.REPLICA_SELECTED,
            observed_watermark=observed,
        )


class StrictPrimaryPolicy(ReadConsistencyPolicyPort):
    """Explicit strong-consistency strategy routing directly to the Pod's Primary Writer."""

    def validate_probe_configuration(
        self,
        watermark_probe: ReplicaWatermarkProbePort | None,
    ) -> None:
        _ = watermark_probe

    def select_route(
        self,
        endpoint: ShardEndpointDTO,
        watermark_probe: ReplicaWatermarkProbePort | None,
        fallback_bulkhead: WriterFallbackBulkheadPort,
    ) -> ReadRouteDecisionDTO:
        _ = (watermark_probe, fallback_bulkhead)
        return ReadRouteDecisionDTO(
            target_role=ReadTargetRole.WRITER,
            target_dsn=endpoint.writer_dsn,
            pool_key=f"{endpoint.shard_id}:{ReadTargetRole.WRITER.value}",
            disposition=ReadRouteDisposition.PRIMARY_SELECTED,
            observed_watermark=None,
        )


class CausalWatermarkPolicy(ReadConsistencyPolicyPort):
    """Guarantees Read-Your-Own-Writes using causal 64-bit `ReplicationWatermark` fencing."""

    def __init__(self, required_watermark: ReplicationWatermark) -> None:
        self._required_watermark = required_watermark

    def validate_probe_configuration(
        self,
        watermark_probe: ReplicaWatermarkProbePort | None,
    ) -> None:
        if watermark_probe is None:
            raise ValueError(
                "A live ReplicaWatermarkProbePort must be supplied to serve causal watermark reads."
            )

    def select_route(
        self,
        endpoint: ShardEndpointDTO,
        watermark_probe: ReplicaWatermarkProbePort | None,
        fallback_bulkhead: WriterFallbackBulkheadPort,
    ) -> ReadRouteDecisionDTO:
        self.validate_probe_configuration(watermark_probe)
        replayed = (
            watermark_probe.get_cached_watermark(endpoint.shard_id)
            if watermark_probe is not None
            else None
        )
        if replayed is not None and replayed >= self._required_watermark:
            return ReadRouteDecisionDTO(
                target_role=ReadTargetRole.READER,
                target_dsn=endpoint.reader_dsn,
                pool_key=f"{endpoint.shard_id}:{ReadTargetRole.READER.value}",
                disposition=ReadRouteDisposition.REPLICA_SELECTED,
                observed_watermark=replayed,
            )

        if fallback_bulkhead.try_acquire_writer_fallback(endpoint.shard_id):
            logger.info(
                "causal_watermark_writer_fallback_routed",
                shard_id=endpoint.shard_id,
                required_watermark=int(self._required_watermark),
                observed_watermark=int(replayed) if replayed is not None else None,
            )
            return ReadRouteDecisionDTO(
                target_role=ReadTargetRole.WRITER,
                target_dsn=endpoint.writer_dsn,
                pool_key=f"{endpoint.shard_id}:{ReadTargetRole.WRITER.value}",
                disposition=ReadRouteDisposition.CAUSAL_WRITER_FALLBACK,
                observed_watermark=replayed,
            )

        logger.error(
            "causal_watermark_fallback_degraded_to_reader",
            shard_id=endpoint.shard_id,
            required_watermark=int(self._required_watermark),
            observed_watermark=int(replayed) if replayed is not None else None,
        )
        return ReadRouteDecisionDTO(
            target_role=ReadTargetRole.READER,
            target_dsn=endpoint.reader_dsn,
            pool_key=f"{endpoint.shard_id}:{ReadTargetRole.READER.value}",
            disposition=ReadRouteDisposition.CAUSAL_BULKHEAD_DEGRADED,
            observed_watermark=replayed,
        )


__all__ = [
    "CausalWatermarkPolicy",
    "EventualReplicaPolicy",
    "InMemoryReplicaWatermarkStore",
    "StrictPrimaryPolicy",
    "TokenBucketWriterFallbackBulkhead",
]
