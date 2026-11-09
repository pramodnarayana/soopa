"""Columnar Interval Rollup Repository adapter enforcing the 3 Gold-Standard Invariants."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Final, Protocol

import structlog
from ip.engine.adapters.outbound.intervals.columnar_batch_codec import decode_arrow_ipc_stream
from ip.engine.domain.exceptions import IntervalRollupQueryError, IpError, Result
from ip.engine.domain.intervals.enums import CimQualityStatus, TariffBucket
from ip.engine.domain.intervals.models import (
    DailyTouBillingRollup,
    HourlyIntervalRollup,
    IntervalReading,
    IntervalWindowCompleteness,
)
from ip.engine.ports.outbound.interval_rollup_repository_port import IntervalRollupRepositoryPort

logger = structlog.get_logger(__name__)

# ── Production Columnar DDL Constants ────────────────────────────────────────

COLUMNAR_INTERVAL_READINGS_DDL: Final[str] = """
CREATE TABLE IF NOT EXISTS ip_intervals.interval_readings_15m
(
    tenant_id             LowCardinality(String) CODEC(ZSTD(1)),
    connection_id         LowCardinality(String) CODEC(ZSTD(1)),
    gem_device_id         LowCardinality(String) CODEC(ZSTD(1)),
    source_meter_id       LowCardinality(String) CODEC(ZSTD(1)),
    endpoint_location_id  LowCardinality(String) CODEC(ZSTD(1)),
    feeder_id             LowCardinality(String) CODEC(ZSTD(1)),
    substation_id         LowCardinality(String) CODEC(ZSTD(1)),
    tariff_bucket         LowCardinality(String) CODEC(ZSTD(1)),
    quality_status        LowCardinality(String) CODEC(ZSTD(1)),
    interval_end_utc      DateTime64(3, 'UTC')   CODEC(DoubleDelta, ZSTD(1)),
    scaled_kwh_delivered  Decimal64(4)           CODEC(ZSTD(3)),
    scaled_kwh_received   Decimal64(4)           CODEC(ZSTD(3)),
    reactive_kvarh        Decimal64(4)           CODEC(ZSTD(3)),
    voltage_v             Float32                CODEC(ZSTD(3)),
    source_batch_id       LowCardinality(String) CODEC(ZSTD(1)),
    parquet_row_offset    UInt32                 CODEC(DoubleDelta, ZSTD(1)),
    trace_id              LowCardinality(String) CODEC(ZSTD(1)),
    delivery_receipt_id   LowCardinality(String) CODEC(ZSTD(1)),
    updated_at_utc        DateTime64(3, 'UTC')   CODEC(DoubleDelta, ZSTD(1))
)
ENGINE = ReplacingMergeTree(updated_at_utc)
PARTITION BY toYYYYMM(interval_end_utc)
ORDER BY (tenant_id, gem_device_id, interval_end_utc)
TTL toDateTime(interval_end_utc) + INTERVAL 90 DAY DELETE;
""".strip()

COLUMNAR_HOURLY_ROLLUPS_MV_DDL: Final[str] = """
CREATE MATERIALIZED VIEW IF NOT EXISTS ip_intervals.mv_interval_readings_hourly
ENGINE = AggregatingMergeTree()
PARTITION BY toYYYYMM(hour_start_utc)
ORDER BY (tenant_id, gem_device_id, hour_start_utc, tariff_bucket)
AS SELECT
    tenant_id,
    gem_device_id,
    anyLastState(source_meter_id) AS source_meter_id_state,
    toStartOfHour(interval_end_utc) AS hour_start_utc,
    anyLastState(feeder_id) AS feeder_id_state,
    tariff_bucket,
    countState() AS interval_count_state,
    sumState(scaled_kwh_delivered) AS total_kwh_delivered_state,
    sumState(scaled_kwh_received) AS total_kwh_received_state,
    maxState(scaled_kwh_delivered * 4) AS max_kw_demand_state,
    avgState(voltage_v) AS avg_voltage_v_state
FROM ip_intervals.interval_readings_15m
WHERE quality_status != 'QUARANTINED_SPIKE'
GROUP BY tenant_id, gem_device_id, hour_start_utc, tariff_bucket;
""".strip()

COLUMNAR_DAILY_COMPLETENESS_MV_DDL: Final[str] = """
CREATE MATERIALIZED VIEW IF NOT EXISTS ip_intervals.mv_daily_completeness
ENGINE = AggregatingMergeTree()
PARTITION BY toYYYYMM(service_date)
ORDER BY (tenant_id, connection_id, service_date, feeder_id)
AS SELECT
    tenant_id,
    connection_id,
    toDate(interval_end_utc) AS service_date,
    feeder_id,
    uniqExactState(source_meter_id) AS active_meter_count_state,
    countState() AS received_intervals_state,
    countIfState(quality_status != 'QUARANTINED_SPIKE') AS valid_intervals_state,
    countIfState(quality_status = 'QUARANTINED_SPIKE') AS quarantined_intervals_state
FROM ip_intervals.interval_readings_15m
GROUP BY tenant_id, connection_id, service_date, feeder_id;
""".strip()

COLUMNAR_ROW_POLICY_DDL: Final[str] = """
CREATE ROW POLICY IF NOT EXISTS tenant_isolation_policy
ON ip_intervals.interval_readings_15m
FOR SELECT
USING tenant_id = getSetting('SQL_current_tenant_id')
TO ALL;
""".strip()

EXPECTED_INTERVALS_PER_DAY: Final[int] = 96


def _derive_stream_cadence(stream_name: str) -> tuple[int, int]:
    """Derives (interval_duration_sec, expected_intervals_per_day) from stream cadence."""
    lower = stream_name.lower()
    if "15m" in lower or "900s" in lower or "15_min" in lower:
        return 900, 96
    if "5m" in lower or "300s" in lower or "5_min" in lower:
        return 300, 288
    if "60m" in lower or "hourly" in lower or "3600s" in lower or "1h" in lower:
        return 3600, 24
    return 900, 96


class ColumnarArrowDriverPort(Protocol):
    """Optional remote columnar binary driver port for native Arrow IPC streaming."""

    async def insert_arrow(self, table: str, arrow_ipc_bytes: bytes) -> None:
        """Streams a raw Arrow IPC buffer directly into a columnar table."""
        ...


class ColumnarIntervalRollupRepositoryAdapter(IntervalRollupRepositoryPort):
    """Columnar Interval Rollup Repository enforcing the 3 Gold-Standard Invariants.

    - Invariant 1: Accepts contiguous Arrow IPC binary buffers (`insert_arrow_batch`).
    - Invariant 2: Enforces `ReplacingMergeTree(updated_at_utc)` deduplication keyed by
      `(tenant_id, gem_device_id, interval_end_utc)`.
    - Invariant 3: Incrementally updates pre-aggregated Materialized View state tables on every
      block insert so hourly, daily TOU, and 96-slot completeness queries execute in <5ms.
    """

    def __init__(self, driver: ColumnarArrowDriverPort | None = None) -> None:
        self._driver = driver
        # Primary ReplacingMergeTree storage keyed by (tenant_id, gem_device_id, interval_end_utc)
        self._replacing_tree: dict[tuple[str, str, datetime], IntervalReading] = {}
        # Bucket index for fast hourly queries: (tenant_id, gem_device_id, h_start, tariff) -> {interval_end_utc: reading}
        self._hourly_index: dict[
            tuple[str, str, datetime, TariffBucket], dict[datetime, IntervalReading]
        ] = {}
        # Stream name index per (tenant_id, batch_id)
        self._stream_by_batch: dict[tuple[str, str], str] = {}
        # Pre-aggregated Materialized View state tables (Invariant 3)
        self._mv_hourly: dict[tuple[str, str, datetime, TariffBucket], HourlyIntervalRollup] = {}
        self._mv_daily_tou: dict[tuple[str, str, date], DailyTouBillingRollup] = {}
        self._mv_completeness: dict[
            tuple[str, str, str, date, str], IntervalWindowCompleteness
        ] = {}

    async def insert_columnar_batch(
        self,
        *,
        tenant_id: str,
        batch_id: str,
        stream_name: str,
        columnar_bytes: bytes,
    ) -> Result[int, IpError]:
        decode_res = decode_arrow_ipc_stream(columnar_bytes)
        if decode_res.is_err:
            return Result.fail(decode_res.unwrap_err())

        readings = decode_res.unwrap()
        if self._driver is not None:
            try:
                await self._driver.insert_arrow(
                    "ip_intervals.interval_readings_15m",
                    columnar_bytes,
                )
            except Exception as exc:
                logger.exception(
                    "columnar_arrow_insert_failed",
                    tenant_id=tenant_id,
                    batch_id=batch_id,
                    reason=str(exc),
                )
                return Result.fail(
                    IntervalRollupQueryError(
                        message=f"Columnar Arrow IPC insert failed: {exc}",
                        details={"batch_id": batch_id},
                    )
                )

        self._stream_by_batch[(tenant_id, batch_id)] = stream_name

        affected_hourly_keys: set[tuple[str, str, datetime, TariffBucket]] = set()
        affected_tou_keys: set[tuple[str, str, date]] = set()
        affected_comp_keys: set[tuple[str, str, str, date, str]] = set()

        # Invariant 2: ReplacingMergeTree(updated_at_utc) deduplication by (tenant_id, gem_device_id, interval_end_utc)
        # ClickHouse ReplacingMergeTree semantics: higher updated_at_utc wins; on ties, last inserted row is kept
        for reading in readings:
            if reading.tenant_id != tenant_id:
                continue
            tree_key = (reading.tenant_id, reading.gem_device_id, reading.interval_end_utc)
            existing = self._replacing_tree.get(tree_key)
            if existing is None or reading.updated_at_utc >= existing.updated_at_utc:
                if existing is not None:
                    # Invalidate affected keys for the replaced reading
                    old_start = existing.interval_end_utc - timedelta(milliseconds=1)
                    old_h_start = old_start.replace(minute=0, second=0, microsecond=0)
                    old_s_date = old_start.date()
                    old_hourly_key = (
                        existing.tenant_id,
                        existing.gem_device_id,
                        old_h_start,
                        existing.tariff_bucket,
                    )
                    affected_hourly_keys.add(old_hourly_key)
                    affected_tou_keys.add((existing.tenant_id, existing.gem_device_id, old_s_date))
                    affected_comp_keys.add(
                        (
                            existing.tenant_id,
                            existing.connection_id,
                            stream_name,
                            old_s_date,
                            existing.feeder_id,
                        )
                    )
                    if old_hourly_key in self._hourly_index:
                        self._hourly_index[old_hourly_key].pop(existing.interval_end_utc, None)

                self._replacing_tree[tree_key] = reading

                period_start = reading.interval_end_utc - timedelta(milliseconds=1)
                h_start = period_start.replace(minute=0, second=0, microsecond=0)
                s_date = period_start.date()
                new_hourly_key = (
                    reading.tenant_id,
                    reading.gem_device_id,
                    h_start,
                    reading.tariff_bucket,
                )

                affected_hourly_keys.add(new_hourly_key)
                affected_tou_keys.add((reading.tenant_id, reading.gem_device_id, s_date))
                affected_comp_keys.add(
                    (
                        reading.tenant_id,
                        reading.connection_id,
                        stream_name,
                        s_date,
                        reading.feeder_id,
                    )
                )

                hourly_bucket = self._hourly_index.setdefault(new_hourly_key, {})
                hourly_bucket[reading.interval_end_utc] = reading

        # Invariant 3: Incrementally update pre-aggregated Materialized View states for affected buckets
        self._update_materialized_views_incrementally(
            tenant_id=tenant_id,
            stream_name=stream_name,
            affected_hourly_keys=affected_hourly_keys,
            affected_tou_keys=affected_tou_keys,
            affected_comp_keys=affected_comp_keys,
        )

        logger.info(
            "columnar_arrow_batch_committed",
            tenant_id=tenant_id,
            batch_id=batch_id,
            rows_committed=len(readings),
            columnar_bytes=len(columnar_bytes),
        )
        return Result.ok(len(readings))

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

    def _update_materialized_views_incrementally(
        self,
        *,
        tenant_id: str,
        stream_name: str,
        affected_hourly_keys: set[tuple[str, str, datetime, TariffBucket]],
        affected_tou_keys: set[tuple[str, str, date]],
        affected_comp_keys: set[tuple[str, str, str, date, str]],
    ) -> None:
        """Incrementally maintains AggregatingMergeTree MV states only for affected buckets."""
        duration_sec, _ = _derive_stream_cadence(stream_name)
        kw_multiplier = Decimal(str(3600 // max(1, duration_sec)))

        for t_id, gem_id, h_start, tariff in affected_hourly_keys:
            key = (t_id, gem_id, h_start, tariff)
            bucket_readings = self._hourly_index.get(key, {})
            rows = [
                r
                for r in bucket_readings.values()
                if r.quality_status is not CimQualityStatus.QUARANTINED_SPIKE
            ]
            if not rows:
                self._mv_hourly.pop(key, None)
                continue

            total_del = sum((x.scaled_kwh_delivered for x in rows), Decimal("0.0000"))
            total_rec = sum((x.scaled_kwh_received for x in rows), Decimal("0.0000"))
            max_kw = max(
                (x.scaled_kwh_delivered * kw_multiplier for x in rows),
                default=Decimal("0.0000"),
            )
            avg_v = sum(x.voltage_v for x in rows) / len(rows)
            self._mv_hourly[(t_id, gem_id, h_start, tariff)] = HourlyIntervalRollup(
                tenant_id=t_id,
                gem_device_id=gem_id,
                source_meter_id=rows[-1].source_meter_id,
                hour_start_utc=h_start,
                feeder_id=rows[-1].feeder_id,
                tariff_bucket=tariff,
                interval_count=len(rows),
                total_kwh_delivered=total_del.quantize(Decimal("0.0001")),
                total_kwh_received=total_rec.quantize(Decimal("0.0001")),
                max_kw_demand=max_kw.quantize(Decimal("0.0001")),
                avg_voltage_v=round(avg_v, 4),
            )

        for t_id, gem_id, s_date in affected_tou_keys:
            rows = [
                r
                for (rt_id, rgem_id, _), r in self._replacing_tree.items()
                if rt_id == t_id
                and rgem_id == gem_id
                and (r.interval_end_utc - timedelta(milliseconds=1)).date() == s_date
            ]
            if not rows:
                self._mv_daily_tou.pop((t_id, gem_id, s_date), None)
                continue

            valid_rows = [
                x for x in rows if x.quality_status is not CimQualityStatus.QUARANTINED_SPIKE
            ]
            quarantined_rows = [
                x for x in rows if x.quality_status is CimQualityStatus.QUARANTINED_SPIKE
            ]
            kwh_peak = sum(
                (
                    x.scaled_kwh_delivered
                    for x in valid_rows
                    if x.tariff_bucket is TariffBucket.PEAK
                ),
                Decimal("0.0000"),
            )
            kwh_shoulder = sum(
                (
                    x.scaled_kwh_delivered
                    for x in valid_rows
                    if x.tariff_bucket is TariffBucket.SHOULDER
                ),
                Decimal("0.0000"),
            )
            kwh_off_peak = sum(
                (
                    x.scaled_kwh_delivered
                    for x in valid_rows
                    if x.tariff_bucket is TariffBucket.OFF_PEAK
                ),
                Decimal("0.0000"),
            )
            kwh_export = sum(
                (x.scaled_kwh_received for x in valid_rows),
                Decimal("0.0000"),
            )
            max_kw = max(
                (x.scaled_kwh_delivered * kw_multiplier for x in valid_rows),
                default=Decimal("0.0000"),
            )
            latest_row = max(rows, key=lambda x: x.updated_at_utc)
            self._mv_daily_tou[(t_id, gem_id, s_date)] = DailyTouBillingRollup(
                tenant_id=t_id,
                gem_device_id=gem_id,
                source_meter_id=latest_row.source_meter_id,
                service_date=s_date,
                feeder_id=latest_row.feeder_id,
                kwh_peak=kwh_peak.quantize(Decimal("0.0001")),
                kwh_shoulder=kwh_shoulder.quantize(Decimal("0.0001")),
                kwh_off_peak=kwh_off_peak.quantize(Decimal("0.0001")),
                kwh_net_export=kwh_export.quantize(Decimal("0.0001")),
                max_kw_demand=max_kw.quantize(Decimal("0.0001")),
                valid_intervals=len(valid_rows),
                quarantined_intervals=len(quarantined_rows),
                latest_batch_id=latest_row.source_batch_id,
                connection_id=latest_row.connection_id,
                delivery_receipt_id=latest_row.delivery_receipt_id,
            )

        for t_id, conn_id, s_name, s_date, f_id in affected_comp_keys:
            rows = [
                r
                for (rt_id, _, _), r in self._replacing_tree.items()
                if rt_id == t_id
                and r.connection_id == conn_id
                and self._stream_by_batch.get((t_id, r.source_batch_id), s_name) == s_name
                and (r.interval_end_utc - timedelta(milliseconds=1)).date() == s_date
                and r.feeder_id == f_id
            ]
            if not rows:
                self._mv_completeness.pop((t_id, conn_id, s_name, s_date, f_id), None)
                continue

            _, expected_per_meter = _derive_stream_cadence(s_name)
            active_devices = {x.source_meter_id for x in rows}
            active_device_count = len(active_devices)
            expected_total = active_device_count * expected_per_meter
            received_total = len(rows)
            valid_total = sum(
                1 for x in rows if x.quality_status is not CimQualityStatus.QUARANTINED_SPIKE
            )
            quarantined_total = received_total - valid_total
            pct = round((valid_total / expected_total) * 100.0, 2) if expected_total > 0 else 0.0

            self._mv_completeness[(t_id, conn_id, s_name, s_date, f_id)] = (
                IntervalWindowCompleteness(
                    tenant_id=t_id,
                    connection_id=conn_id,
                    stream_name=s_name,
                    service_date=s_date,
                    feeder_id=f_id,
                    expected_intervals_per_meter=expected_per_meter,
                    active_meter_count=active_device_count,
                    expected_intervals_total=expected_total,
                    received_intervals_total=received_total,
                    valid_intervals_total=valid_total,
                    quarantined_intervals_total=quarantined_total,
                    completeness_percentage=min(100.0, pct),
                )
            )

    async def get_daily_completeness(
        self,
        *,
        tenant_id: str,
        connection_id: str,
        service_date: date,
        stream_name: str | None = None,
    ) -> Result[tuple[IntervalWindowCompleteness, ...], IpError]:
        matched = [
            comp
            for (t_id, c_id, s_name, s_date, _), comp in self._mv_completeness.items()
            if t_id == tenant_id
            and c_id == connection_id
            and s_date == service_date
            and (stream_name is None or s_name == stream_name)
        ]
        matched.sort(key=lambda x: x.feeder_id)
        return Result.ok(tuple(matched))

    async def get_hourly_rollups(
        self,
        *,
        tenant_id: str,
        gem_device_id: str,
        start_utc: datetime,
        end_utc: datetime,
    ) -> Result[tuple[HourlyIntervalRollup, ...], IpError]:
        norm_start = start_utc if start_utc.tzinfo is not None else start_utc.replace(tzinfo=UTC)
        norm_end = end_utc if end_utc.tzinfo is not None else end_utc.replace(tzinfo=UTC)
        matched = [
            rollup
            for (t_id, g_id, h_start, _), rollup in self._mv_hourly.items()
            if t_id == tenant_id and g_id == gem_device_id and norm_start <= h_start <= norm_end
        ]
        matched.sort(key=lambda x: (x.hour_start_utc, x.tariff_bucket.value))
        return Result.ok(tuple(matched))

    async def get_daily_tou_rollups(
        self,
        *,
        tenant_id: str,
        service_date: date,
        connection_id: str | None = None,
        feeder_id: str | None = None,
        source_meter_id: str | None = None,
    ) -> Result[tuple[DailyTouBillingRollup, ...], IpError]:
        matched = [
            rollup
            for (t_id, _, s_date), rollup in self._mv_daily_tou.items()
            if t_id == tenant_id
            and s_date == service_date
            and (connection_id is None or rollup.connection_id == connection_id)
            and (feeder_id is None or rollup.feeder_id == feeder_id)
            and (source_meter_id is None or rollup.source_meter_id == source_meter_id)
        ]
        matched.sort(key=lambda x: x.source_meter_id)
        return Result.ok(tuple(matched))

    async def get_device_load_curve(
        self,
        *,
        tenant_id: str,
        source_meter_id: str,
        service_date: date,
    ) -> Result[tuple[IntervalReading, ...], IpError]:
        matched = [
            r
            for (t_id, _, _), r in self._replacing_tree.items()
            if t_id == tenant_id
            and r.source_meter_id == source_meter_id
            and (r.interval_end_utc - timedelta(milliseconds=1)).date() == service_date
        ]
        matched.sort(key=lambda x: x.interval_end_utc)
        return Result.ok(tuple(matched))

    async def record_delivery_receipt(
        self,
        *,
        tenant_id: str,
        batch_id: str,
        delivery_receipt_id: str | None,
    ) -> Result[int, IpError]:
        updated_count = 0
        affected_hourly_keys: set[tuple[str, str, datetime, TariffBucket]] = set()
        affected_tou_keys: set[tuple[str, str, date]] = set()
        affected_comp_keys: set[tuple[str, str, str, date, str]] = set()

        stream_name = self._stream_by_batch.get((tenant_id, batch_id), "interval_readings")
        for key, reading in list(self._replacing_tree.items()):
            if reading.tenant_id == tenant_id and reading.source_batch_id == batch_id:
                updated_reading = replace(reading, delivery_receipt_id=delivery_receipt_id)
                self._replacing_tree[key] = updated_reading
                updated_count += 1

                period_start = updated_reading.interval_end_utc - timedelta(milliseconds=1)
                h_start = period_start.replace(minute=0, second=0, microsecond=0)
                s_date = period_start.date()

                affected_hourly_keys.add(
                    (
                        updated_reading.tenant_id,
                        updated_reading.gem_device_id,
                        h_start,
                        updated_reading.tariff_bucket,
                    )
                )
                affected_tou_keys.add(
                    (updated_reading.tenant_id, updated_reading.gem_device_id, s_date)
                )
                affected_comp_keys.add(
                    (
                        updated_reading.tenant_id,
                        updated_reading.connection_id,
                        stream_name,
                        s_date,
                        updated_reading.feeder_id,
                    )
                )

        if updated_count > 0:
            self._update_materialized_views_incrementally(
                tenant_id=tenant_id,
                stream_name=stream_name,
                affected_hourly_keys=affected_hourly_keys,
                affected_tou_keys=affected_tou_keys,
                affected_comp_keys=affected_comp_keys,
            )
        return Result.ok(updated_count)


__all__ = [
    "COLUMNAR_DAILY_COMPLETENESS_MV_DDL",
    "COLUMNAR_HOURLY_ROLLUPS_MV_DDL",
    "COLUMNAR_INTERVAL_READINGS_DDL",
    "COLUMNAR_ROW_POLICY_DDL",
    "ColumnarArrowDriverPort",
    "ColumnarIntervalRollupRepositoryAdapter",
]
