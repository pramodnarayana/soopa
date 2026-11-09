"""Outbound port for vectorized columnar L2/L3 interval batch normalization."""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from ip.engine.domain.exceptions import IpError, Result
from ip.engine.domain.intervals.enums import IntervalPayloadFormat
from ip.engine.domain.intervals.models import (
    BatchReconciliationCounts,
    FeederOutageCluster,
    IntervalReading,
    StormAggregationPolicy,
    VeeValidationPolicy,
)


@dataclass(frozen=True, slots=True)
class ColumnarNormalizedBatchDTO:
    """Immutable result of vectorized L2/L3 interval batch normalization.

    Contains:
    - `arrow_ipc_bytes`: Contiguous zero-copy binary columnar Arrow IPC stream buffer
      ready for direct streaming into the columnar rollup store (Invariant 1).
    - `canonical_readings`: Validated & VEE-tagged canonical readings (including quarantined spikes
      marked with `CimQualityStatus.QUARANTINED_SPIKE` so every interval is accounted for).
    - `counts`: Zero-Loss Accounting Equation counts (`raw == dropped + valid + quarantined`).
    - `outage_clusters`: Storm-grouped `0.0V` feeder outage clusters ready for P0_CRITICAL promotion.
    """

    batch_id: str
    tenant_id: str
    connection_id: str
    stream_name: str
    arrow_ipc_bytes: bytes
    canonical_readings: tuple[IntervalReading, ...]
    counts: BatchReconciliationCounts
    outage_clusters: tuple[FeederOutageCluster, ...]


class ColumnarBatchProcessorPort(Protocol):
    """Outbound port for vectorized in-memory interval batch processing."""

    @abstractmethod
    def normalize_batch(
        self,
        *,
        batch_id: str,
        tenant_id: str,
        connection_id: str,
        stream_name: str,
        trace_id: str,
        raw_payload_bytes: bytes,
        payload_format: IntervalPayloadFormat = IntervalPayloadFormat.JSON_ARRAY,
        gem_crosswalk: Mapping[str, str] | None = None,
        storm_policy: StormAggregationPolicy | None = None,
        vee_policy: VeeValidationPolicy | None = None,
    ) -> Result[ColumnarNormalizedBatchDTO, IpError]:
        """Executes vectorized deduplication, GEM dictionary resolution, VEE spike guard, and storm clustering."""
        ...


__all__ = [
    "ColumnarBatchProcessorPort",
    "ColumnarNormalizedBatchDTO",
]
