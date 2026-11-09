"""Vectorized Interval Batch Normalizer adapter for High-Frequency Interval Streams."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from statistics import median

import structlog
from ip.engine.adapters.outbound.intervals.columnar_batch_codec import (
    decode_arrow_ipc_stream,
    encode_arrow_ipc_stream,
)
from ip.engine.domain.constants import IpIdPrefix
from ip.engine.domain.exceptions import (
    IntervalMalformedBatchError,
    IpError,
    Result,
)
from ip.engine.domain.intervals.enums import (
    CimQualityStatus,
    IntervalPayloadFormat,
    TariffBucket,
)
from ip.engine.domain.intervals.models import (
    BatchReconciliationCounts,
    FeederOutageCluster,
    IntervalReading,
    StormAggregationPolicy,
    VeeValidationPolicy,
)
from ip.engine.ports.outbound.columnar_batch_processor_port import (
    ColumnarBatchProcessorPort,
    ColumnarNormalizedBatchDTO,
)
from seedwork.utils import generate_id

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class _ParsedRawInterval:
    """Internal columnar staging tuple for a parsed raw interval row."""

    row_offset: int
    source_meter_id: str
    endpoint_location_id: str
    feeder_id: str
    substation_id: str
    interval_end_utc: datetime
    kwh_delivered: Decimal
    kwh_received: Decimal
    reactive_kvarh: Decimal
    voltage_v: float
    multiplier: Decimal
    explicit_tariff: TariffBucket | None
    explicit_quality: CimQualityStatus | None


def _classify_tariff_bucket(interval_end_utc: datetime) -> TariffBucket:
    """Classifies a UTC interval timestamp into Peak, Shoulder, or Off-Peak TOU bucket."""
    if interval_end_utc.weekday() >= 5:
        return TariffBucket.OFF_PEAK
    hour = interval_end_utc.hour
    if 16 <= hour < 21:
        return TariffBucket.PEAK
    if 7 <= hour < 16 or 21 <= hour < 23:
        return TariffBucket.SHOULDER
    return TariffBucket.OFF_PEAK


def _deterministic_gem_id(tenant_id: str, connection_id: str, source_meter_id: str) -> str:
    digest = hashlib.sha256(f"{tenant_id}:{connection_id}:{source_meter_id}".encode()).hexdigest()[
        :16
    ]
    return f"{IpIdPrefix.GEM.value}_{digest}"


def _parse_decimal(raw_val: object, default: str = "0.0000") -> Decimal:
    if raw_val is None or raw_val == "":
        return Decimal(default)
    try:
        return Decimal(str(raw_val))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Invalid decimal value '{raw_val}'") from exc


def _parse_timestamp(raw_ts: object) -> datetime:
    if not isinstance(raw_ts, str) or not raw_ts.strip():
        raise ValueError("Missing interval_end_utc timestamp.")
    normalized = raw_ts.strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _compute_device_medians(
    unique_rows: list[_ParsedRawInterval],
    max_interval_kwh: Decimal,
) -> dict[str, Decimal]:
    kwh_by_device: dict[str, list[Decimal]] = {}
    for row in unique_rows:
        scaled_del = (row.kwh_delivered * row.multiplier).quantize(Decimal("0.0001"))
        if Decimal("0") <= scaled_del <= max_interval_kwh:
            kwh_by_device.setdefault(row.source_meter_id, []).append(scaled_del)

    median_by_device: dict[str, Decimal] = {}
    for m_id, values in kwh_by_device.items():
        if len(values) >= 3:
            median_by_device[m_id] = Decimal(str(median(values)))
    return median_by_device


def _classify_row_vee_quality(
    *,
    row: _ParsedRawInterval,
    scaled_del: Decimal,
    device_median: Decimal | None,
    vee_policy: VeeValidationPolicy,
    storm_policy: StormAggregationPolicy,
) -> tuple[CimQualityStatus, str | None]:
    if row.explicit_quality is CimQualityStatus.QUARANTINED_SPIKE:
        return CimQualityStatus.QUARANTINED_SPIKE, "Explicit upstream QUARANTINED_SPIKE flag"
    if scaled_del < Decimal("0"):
        return (
            CimQualityStatus.QUARANTINED_SPIKE,
            f"Negative interval reading ({scaled_del} units)",
        )
    if scaled_del > vee_policy.max_interval_kwh:
        return (
            CimQualityStatus.QUARANTINED_SPIKE,
            f"Interval reading ({scaled_del} units) exceeds VEE ceiling ({vee_policy.max_interval_kwh} units)",
        )
    if (
        device_median is not None
        and device_median >= Decimal("0.1000")
        and scaled_del > (device_median * vee_policy.mad_spike_multiplier)
    ):
        return (
            CimQualityStatus.QUARANTINED_SPIKE,
            (
                f"Interval spike ({scaled_del} units) exceeds {vee_policy.mad_spike_multiplier}x "
                f"device median ({device_median} units)"
            ),
        )
    if row.voltage_v <= storm_policy.zero_voltage_threshold:
        return CimQualityStatus.POWER_DOWN, None
    return row.explicit_quality or CimQualityStatus.VALID, None


class VectorizedIntervalBatchNormalizerAdapter(ColumnarBatchProcessorPort):
    """In-memory vectorized L2/L3 interval batch normalizer, VEE validator, and storm clusterer."""

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
        effective_storm = storm_policy or StormAggregationPolicy()
        effective_vee = vee_policy or VeeValidationPolicy()
        crosswalk = gem_crosswalk or {}

        if payload_format is IntervalPayloadFormat.ARROW_IPC:
            return self._normalize_arrow_ipc_passthrough(
                batch_id=batch_id,
                tenant_id=tenant_id,
                connection_id=connection_id,
                stream_name=stream_name,
                trace_id=trace_id,
                raw_payload_bytes=raw_payload_bytes,
                storm_policy=effective_storm,
            )

        parsed_res = self._parse_raw_rows(raw_payload_bytes, payload_format)
        if parsed_res.is_err:
            return Result.fail(parsed_res.unwrap_err())

        raw_rows = parsed_res.unwrap()
        raw_ingested_count = len(raw_rows)
        if raw_ingested_count == 0:
            return Result.fail(
                IntervalMalformedBatchError.with_reason("Interval batch contains 0 interval rows.")
            )

        # Step 1: Vectorized Intra-Batch Deduplication by (source_meter_id, interval_end_utc)
        deduped_by_key: dict[tuple[str, datetime], _ParsedRawInterval] = {
            (row.source_meter_id, row.interval_end_utc): row for row in raw_rows
        }
        unique_rows = list(deduped_by_key.values())
        duplicates_dropped_count = raw_ingested_count - len(unique_rows)

        # Step 2: Compute per-device baseline median for Rolling Spike Quarantine
        median_by_device = _compute_device_medians(unique_rows, effective_vee.max_interval_kwh)

        # Step 3: Vectorized GEM dictionary resolution, CT/PT scaling, and VEE classification
        now_utc = datetime.now(UTC)
        canonical_readings: list[IntervalReading] = []
        valid_canonical_count = 0
        quarantined_held_count = 0

        for row in unique_rows:
            gem_id = crosswalk.get(row.source_meter_id) or _deterministic_gem_id(
                tenant_id, connection_id, row.source_meter_id
            )
            scaled_del = (row.kwh_delivered * row.multiplier).quantize(Decimal("0.0001"))
            scaled_rec = (row.kwh_received * row.multiplier).quantize(Decimal("0.0001"))
            scaled_kvarh = (row.reactive_kvarh * row.multiplier).quantize(Decimal("0.0001"))
            tariff = row.explicit_tariff or _classify_tariff_bucket(row.interval_end_utc)

            quality, quarantine_reason = _classify_row_vee_quality(
                row=row,
                scaled_del=scaled_del,
                device_median=median_by_device.get(row.source_meter_id),
                vee_policy=effective_vee,
                storm_policy=effective_storm,
            )

            if quality is CimQualityStatus.QUARANTINED_SPIKE:
                quarantined_held_count += 1
            else:
                valid_canonical_count += 1

            canonical_readings.append(
                IntervalReading(
                    tenant_id=tenant_id,
                    connection_id=connection_id,
                    gem_device_id=gem_id,
                    source_meter_id=row.source_meter_id,
                    endpoint_location_id=row.endpoint_location_id,
                    feeder_id=row.feeder_id,
                    substation_id=row.substation_id,
                    tariff_bucket=tariff,
                    quality_status=quality,
                    interval_end_utc=row.interval_end_utc,
                    scaled_kwh_delivered=scaled_del,
                    scaled_kwh_received=scaled_rec,
                    reactive_kvarh=scaled_kvarh,
                    voltage_v=row.voltage_v,
                    source_batch_id=batch_id,
                    parquet_row_offset=row.row_offset,
                    trace_id=trace_id,
                    updated_at_utc=now_utc,
                    quarantine_reason=quarantine_reason,
                )
            )

        readings_tuple = tuple(canonical_readings)
        counts = BatchReconciliationCounts(
            raw_ingested=raw_ingested_count,
            duplicates_dropped=duplicates_dropped_count,
            valid_canonical=valid_canonical_count,
            quarantined_held=quarantined_held_count,
        )

        # Step 4: Storm-Safe Spatial Outage Clustering
        outage_clusters = self._cluster_feeder_outages(
            readings=readings_tuple,
            tenant_id=tenant_id,
            connection_id=connection_id,
            batch_id=batch_id,
            trace_id=trace_id,
            storm_policy=effective_storm,
        )

        # Step 5: Encode contiguous binary Arrow IPC stream (Invariant 1)
        arrow_ipc_bytes = encode_arrow_ipc_stream(readings_tuple)

        logger.info(
            "vectorized_interval_batch_normalized",
            tenant_id=tenant_id,
            batch_id=batch_id,
            stream_name=stream_name,
            raw_ingested=raw_ingested_count,
            duplicates_dropped=duplicates_dropped_count,
            valid_canonical=valid_canonical_count,
            quarantined_held=quarantined_held_count,
            outage_clusters_count=len(outage_clusters),
            arrow_ipc_bytes=len(arrow_ipc_bytes),
        )

        return Result.ok(
            ColumnarNormalizedBatchDTO(
                batch_id=batch_id,
                tenant_id=tenant_id,
                connection_id=connection_id,
                stream_name=stream_name,
                arrow_ipc_bytes=arrow_ipc_bytes,
                canonical_readings=readings_tuple,
                counts=counts,
                outage_clusters=outage_clusters,
            )
        )

    def _normalize_arrow_ipc_passthrough(
        self,
        *,
        batch_id: str,
        tenant_id: str,
        connection_id: str,
        stream_name: str,
        trace_id: str,
        raw_payload_bytes: bytes,
        storm_policy: StormAggregationPolicy,
    ) -> Result[ColumnarNormalizedBatchDTO, IpError]:
        decoded_res = decode_arrow_ipc_stream(raw_payload_bytes)
        if decoded_res.is_err:
            return Result.fail(decoded_res.unwrap_err())
        existing_readings = decoded_res.unwrap()
        raw_count = len(existing_readings)
        valid_count = sum(
            1
            for r in existing_readings
            if r.quality_status is not CimQualityStatus.QUARANTINED_SPIKE
        )
        quarantined_count = raw_count - valid_count
        counts = BatchReconciliationCounts(
            raw_ingested=raw_count,
            duplicates_dropped=0,
            valid_canonical=valid_count,
            quarantined_held=quarantined_count,
        )
        clusters = self._cluster_feeder_outages(
            readings=existing_readings,
            tenant_id=tenant_id,
            connection_id=connection_id,
            batch_id=batch_id,
            trace_id=trace_id,
            storm_policy=storm_policy,
        )
        return Result.ok(
            ColumnarNormalizedBatchDTO(
                batch_id=batch_id,
                tenant_id=tenant_id,
                connection_id=connection_id,
                stream_name=stream_name,
                arrow_ipc_bytes=raw_payload_bytes,
                canonical_readings=existing_readings,
                counts=counts,
                outage_clusters=clusters,
            )
        )

    @staticmethod
    def _cluster_feeder_outages(
        *,
        readings: tuple[IntervalReading, ...],
        tenant_id: str,
        connection_id: str,
        batch_id: str,
        trace_id: str,
        storm_policy: StormAggregationPolicy,
    ) -> tuple[FeederOutageCluster, ...]:
        """Groups 0.0V endpoints by (feeder_id, substation_id) and applies the Storm-Safe threshold."""
        endpoints_by_feeder: dict[tuple[str, str], dict[str, datetime]] = {}
        for r in readings:
            if r.voltage_v <= storm_policy.zero_voltage_threshold:
                feeder_key = (r.feeder_id, r.substation_id)
                endpoint_map = endpoints_by_feeder.setdefault(feeder_key, {})
                existing_ts = endpoint_map.get(r.source_meter_id)
                if existing_ts is None or r.interval_end_utc < existing_ts:
                    endpoint_map[r.source_meter_id] = r.interval_end_utc

        clusters: list[FeederOutageCluster] = []
        for (feeder_id, substation_id), endpoint_map in sorted(endpoints_by_feeder.items()):
            sorted_endpoints = tuple(sorted(endpoint_map.keys()))
            outage_count = len(sorted_endpoints)
            earliest_utc = min(endpoint_map.values())

            if outage_count >= storm_policy.storm_threshold_meters:
                # Storm mode: collapse all N endpoints on this feeder into 1 FeederOutageCluster
                clusters.append(
                    FeederOutageCluster(
                        cluster_id=generate_id(IpIdPrefix.OUTAGE_CLUSTER.value),
                        tenant_id=tenant_id,
                        connection_id=connection_id,
                        batch_id=batch_id,
                        feeder_id=feeder_id,
                        substation_id=substation_id,
                        outage_meter_count=outage_count,
                        affected_meter_ids=sorted_endpoints,
                        outage_start_utc=earliest_utc,
                        trace_id=trace_id,
                    )
                )
            else:
                # Normal mode (< threshold): promote individual endpoint outage clusters
                for m_id in sorted_endpoints:
                    clusters.append(
                        FeederOutageCluster(
                            cluster_id=generate_id(IpIdPrefix.OUTAGE_CLUSTER.value),
                            tenant_id=tenant_id,
                            connection_id=connection_id,
                            batch_id=batch_id,
                            feeder_id=feeder_id,
                            substation_id=substation_id,
                            outage_meter_count=1,
                            affected_meter_ids=(m_id,),
                            outage_start_utc=endpoint_map[m_id],
                            trace_id=trace_id,
                        )
                    )
        return tuple(clusters)

    def _parse_raw_rows(
        self,
        raw_payload_bytes: bytes,
        payload_format: IntervalPayloadFormat,
    ) -> Result[tuple[_ParsedRawInterval, ...], IntervalMalformedBatchError]:
        try:
            text_payload = raw_payload_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            return Result.fail(
                IntervalMalformedBatchError.with_reason(
                    f"Unable to decode UTF-8 interval batch: {exc}"
                )
            )

        if payload_format is IntervalPayloadFormat.CSV:
            return self._parse_csv_rows(text_payload)
        return self._parse_json_rows(text_payload)

    def _parse_json_rows(
        self,
        text_payload: str,
    ) -> Result[tuple[_ParsedRawInterval, ...], IntervalMalformedBatchError]:
        try:
            decoded = json.loads(text_payload)
        except json.JSONDecodeError as exc:
            return Result.fail(
                IntervalMalformedBatchError.with_reason(f"Malformed JSON interval batch: {exc}")
            )

        if isinstance(decoded, dict) and isinstance(decoded.get("readings"), list):
            raw_list = decoded["readings"]
        elif isinstance(decoded, list):
            raw_list = decoded
        else:
            return Result.fail(
                IntervalMalformedBatchError.with_reason(
                    "JSON interval payload must be a list or contain a 'readings' list."
                )
            )

        parsed: list[_ParsedRawInterval] = []
        for idx, item in enumerate(raw_list):
            if not isinstance(item, dict):
                return Result.fail(
                    IntervalMalformedBatchError.with_reason(
                        f"Row at offset {idx} is not a JSON object."
                    )
                )
            row_res = self._extract_row_fields(idx, item)
            if row_res.is_err:
                return Result.fail(row_res.unwrap_err())
            parsed.append(row_res.unwrap())
        return Result.ok(tuple(parsed))

    def _parse_csv_rows(
        self,
        text_payload: str,
    ) -> Result[tuple[_ParsedRawInterval, ...], IntervalMalformedBatchError]:
        reader = csv.DictReader(io.StringIO(text_payload))
        parsed: list[_ParsedRawInterval] = []
        for idx, item in enumerate(reader):
            row_res = self._extract_row_fields(idx, item)
            if row_res.is_err:
                return Result.fail(row_res.unwrap_err())
            parsed.append(row_res.unwrap())
        return Result.ok(tuple(parsed))

    @staticmethod
    def _extract_row_fields(
        row_offset: int,
        item: Mapping[str, object],
    ) -> Result[_ParsedRawInterval, IntervalMalformedBatchError]:
        try:
            source_dev_id = str(
                item.get("source_meter_id") or item.get("source_device_id") or ""
            ).strip()
            if not source_dev_id:
                return Result.fail(
                    IntervalMalformedBatchError.with_reason(
                        f"Row at offset {row_offset} is missing 'source_meter_id'."
                    )
                )
            endpoint_loc_id = str(
                item.get("endpoint_location_id") or f"LOC-{source_dev_id}"
            ).strip()
            feeder_id = str(item.get("feeder_id") or "FDR-DEFAULT").strip()
            substation_id = str(item.get("substation_id") or "SUB-DEFAULT").strip()
            interval_end_utc = _parse_timestamp(
                item.get("interval_end_utc") or item.get("timestamp")
            )
            kwh_delivered = _parse_decimal(
                item.get("kwh_delivered", item.get("scaled_kwh_delivered", "0.0000"))
            )
            kwh_received = _parse_decimal(
                item.get("kwh_received", item.get("scaled_kwh_received", "0.0000"))
            )
            reactive_kvarh = _parse_decimal(item.get("reactive_kvarh", "0.0000"))
            voltage_raw = item.get("voltage_v", 240.0)
            voltage_v = float(str(voltage_raw)) if voltage_raw is not None else 240.0
            multiplier = _parse_decimal(item.get("multiplier", "1.0"), default="1.0")

            raw_tariff = item.get("tariff_bucket")
            explicit_tariff = (
                TariffBucket(str(raw_tariff))
                if isinstance(raw_tariff, str) and raw_tariff
                else None
            )
            raw_quality = item.get("quality_status")
            explicit_quality = (
                CimQualityStatus(str(raw_quality))
                if isinstance(raw_quality, str) and raw_quality
                else None
            )

            return Result.ok(
                _ParsedRawInterval(
                    row_offset=row_offset,
                    source_meter_id=source_dev_id,
                    endpoint_location_id=endpoint_loc_id,
                    feeder_id=feeder_id,
                    substation_id=substation_id,
                    interval_end_utc=interval_end_utc,
                    kwh_delivered=kwh_delivered,
                    kwh_received=kwh_received,
                    reactive_kvarh=reactive_kvarh,
                    voltage_v=voltage_v,
                    multiplier=multiplier,
                    explicit_tariff=explicit_tariff,
                    explicit_quality=explicit_quality,
                )
            )
        except (ValueError, TypeError) as exc:
            return Result.fail(
                IntervalMalformedBatchError.with_reason(
                    f"Malformed interval reading at row offset {row_offset}: {exc}"
                )
            )


__all__ = ["VectorizedIntervalBatchNormalizerAdapter"]
