"""Outbound port for the Columnar Interval Rollup Repository."""

from __future__ import annotations

from abc import abstractmethod
from datetime import date, datetime
from typing import Protocol

from ip.engine.domain.exceptions import IpError, Result
from ip.engine.domain.intervals.models import (
    DailyTouBillingRollup,
    HourlyIntervalRollup,
    IntervalReading,
    IntervalWindowCompleteness,
)


class IntervalRollupRepositoryPort(Protocol):
    """Outbound port for high-frequency columnar interval storage and real-time MV rollups.

    Enforces the 3 Gold-Standard Invariants:
    1. Zero-Copy Arrow IPC Streaming (`insert_arrow_batch` accepts raw Arrow IPC bytes).
    2. Idempotent Deduplication (`ReplacingMergeTree(updated_at_utc)` keyed by
       `(tenant_id, gem_device_id, interval_end_utc)`).
    3. Pre-Aggregated Materialized Views (`AggregatingMergeTree` rollups for hourly/daily TOU
       and 96-slot completeness).
    """

    @abstractmethod
    async def insert_columnar_batch(
        self,
        *,
        tenant_id: str,
        batch_id: str,
        stream_name: str,
        columnar_bytes: bytes,
    ) -> Result[int, IpError]:
        """Streams a contiguous binary columnar buffer directly into the columnar store."""
        ...

    async def insert_arrow_batch(
        self,
        *,
        tenant_id: str,
        batch_id: str,
        stream_name: str,
        arrow_ipc_bytes: bytes,
    ) -> Result[int, IpError]:
        """Compatibility bridge delegating to insert_columnar_batch."""
        return await self.insert_columnar_batch(
            tenant_id=tenant_id,
            batch_id=batch_id,
            stream_name=stream_name,
            columnar_bytes=arrow_ipc_bytes,
        )

    @abstractmethod
    async def get_daily_completeness(
        self,
        *,
        tenant_id: str,
        connection_id: str,
        service_date: date,
        stream_name: str | None = None,
    ) -> Result[tuple[IntervalWindowCompleteness, ...], IpError]:
        """Queries the pre-aggregated daily completeness Materialized View (<25ms SLA)."""
        ...

    @abstractmethod
    async def get_hourly_rollups(
        self,
        *,
        tenant_id: str,
        gem_device_id: str,
        start_utc: datetime,
        end_utc: datetime,
    ) -> Result[tuple[HourlyIntervalRollup, ...], IpError]:
        """Queries the pre-aggregated hourly interval rollup Materialized View."""
        ...

    @abstractmethod
    async def get_daily_tou_rollups(
        self,
        *,
        tenant_id: str,
        service_date: date,
        connection_id: str | None = None,
        feeder_id: str | None = None,
        source_meter_id: str | None = None,
    ) -> Result[tuple[DailyTouBillingRollup, ...], IpError]:
        """Queries the Daily Time-of-Use (TOU) Peak/Shoulder/Off-Peak billing rollup."""
        ...

    @abstractmethod
    async def get_device_load_curve(
        self,
        *,
        tenant_id: str,
        source_meter_id: str,
        service_date: date,
    ) -> Result[tuple[IntervalReading, ...], IpError]:
        """Queries the 96-slot 15-min interval load curve for a specific device including batch lineage pointers."""
        ...

    @abstractmethod
    async def record_delivery_receipt(
        self,
        *,
        tenant_id: str,
        batch_id: str,
        delivery_receipt_id: str | None,
    ) -> Result[int, IpError]:
        """Associates a downstream settlement receipt ID (e.g. CIS / billing receipt) with a batch's readings."""
        ...


__all__ = ["IntervalRollupRepositoryPort"]
