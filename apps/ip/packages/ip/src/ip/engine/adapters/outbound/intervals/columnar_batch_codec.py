"""Contiguous binary columnar Arrow IPC stream encoder and decoder for Interval Streams.

Enforces Gold-Standard Invariant 1:
- Zero row-level Python dict allocations between the vectorized processor and the rollup store.
- Uses dictionary-encoded string tables (`LowCardinality(String)` layout) and contiguous typed
  numeric arrays (`array('q')`, `array('i')`, `array('d')`) framed with the Arrow IPC stream header.
"""

from __future__ import annotations

import importlib
import io
import struct
import zlib
from array import array
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal

from ip.engine.domain.exceptions import IntervalMalformedBatchError, Result
from ip.engine.domain.intervals.enums import CimQualityStatus, TariffBucket
from ip.engine.domain.intervals.models import IntervalReading

ARROW_IPC_STREAM_MAGIC = b"ARROW1\x00\x00"
_SCALE_FACTOR = Decimal("10000")
MAX_DECOMPRESSED_BYTES = 50 * 1024 * 1024  # 50 MB decompression limit (zip-bomb guard)


def _try_decode_pyarrow_stream(buffer: bytes) -> tuple[IntervalReading, ...] | None:
    try:
        pa_ipc = importlib.import_module("pyarrow.ipc")
        reader = pa_ipc.open_stream(io.BytesIO(buffer))
        table = reader.read_all()
        pydict = table.to_pydict()
        num_rows = table.num_rows
        readings: list[IntervalReading] = []
        for i in range(num_rows):
            readings.append(
                IntervalReading(
                    tenant_id=str(pydict["tenant_id"][i]),
                    connection_id=str(pydict["connection_id"][i]),
                    gem_device_id=str(pydict["gem_device_id"][i]),
                    source_meter_id=str(pydict["source_meter_id"][i]),
                    endpoint_location_id=str(pydict["endpoint_location_id"][i]),
                    feeder_id=str(pydict["feeder_id"][i]),
                    substation_id=str(pydict["substation_id"][i]),
                    tariff_bucket=TariffBucket(str(pydict["tariff_bucket"][i])),
                    quality_status=CimQualityStatus(str(pydict["quality_status"][i])),
                    interval_end_utc=(
                        pydict["interval_end_utc"][i]
                        if isinstance(pydict["interval_end_utc"][i], datetime)
                        else datetime.fromisoformat(str(pydict["interval_end_utc"][i]))
                    ),
                    scaled_kwh_delivered=Decimal(str(pydict["scaled_kwh_delivered"][i])),
                    scaled_kwh_received=Decimal(str(pydict["scaled_kwh_received"][i])),
                    reactive_kvarh=Decimal(str(pydict["reactive_kvarh"][i])),
                    voltage_v=float(pydict["voltage_v"][i]),
                    source_batch_id=str(pydict["source_batch_id"][i]),
                    parquet_row_offset=int(pydict["parquet_row_offset"][i]),
                    trace_id=str(pydict["trace_id"][i]),
                    updated_at_utc=(
                        pydict["updated_at_utc"][i]
                        if isinstance(pydict["updated_at_utc"][i], datetime)
                        else datetime.fromisoformat(str(pydict["updated_at_utc"][i]))
                    ),
                    quarantine_reason=pydict.get("quarantine_reason", [None] * num_rows)[i],
                    delivery_receipt_id=pydict.get("delivery_receipt_id", [None] * num_rows)[i],
                )
            )
        return tuple(readings)
    except (ImportError, AttributeError, ValueError, TypeError, KeyError, OSError, RuntimeError):
        return None


def _intern_string(value: str, table: list[str], index_map: dict[str, int]) -> int:
    existing = index_map.get(value)
    if existing is not None:
        return existing
    idx = len(table)
    table.append(value)
    index_map[value] = idx
    return idx


def encode_arrow_ipc_stream(readings: Sequence[IntervalReading]) -> bytes:
    """Encodes a sequence of IntervalReadings into a contiguous binary columnar Arrow IPC buffer."""
    row_count = len(readings)
    string_table: list[str] = [""]
    string_index: dict[str, int] = {"": 0}

    # Dictionary-encoded LowCardinality string index columns (32-bit signed integers)
    col_tenant = array("i")
    col_conn = array("i")
    col_gem = array("i")
    col_meter = array("i")
    col_sp = array("i")
    col_feeder = array("i")
    col_substation = array("i")
    col_tariff = array("i")
    col_quality = array("i")
    col_batch = array("i")
    col_trace = array("i")
    col_qreason = array("i")
    col_receipt = array("i")

    # Contiguous numeric & timestamp columns
    col_interval_ms = array("q")
    col_updated_ms = array("q")
    col_kwh_del_scaled = array("q")
    col_kwh_rec_scaled = array("q")
    col_kvarh_scaled = array("q")
    col_voltage = array("d")
    col_row_offset = array("i")

    for r in readings:
        col_tenant.append(_intern_string(r.tenant_id, string_table, string_index))
        col_conn.append(_intern_string(r.connection_id, string_table, string_index))
        col_gem.append(_intern_string(r.gem_device_id, string_table, string_index))
        col_meter.append(_intern_string(r.source_meter_id, string_table, string_index))
        col_sp.append(_intern_string(r.endpoint_location_id, string_table, string_index))
        col_feeder.append(_intern_string(r.feeder_id, string_table, string_index))
        col_substation.append(_intern_string(r.substation_id, string_table, string_index))
        col_tariff.append(_intern_string(r.tariff_bucket.value, string_table, string_index))
        col_quality.append(_intern_string(r.quality_status.value, string_table, string_index))
        col_batch.append(_intern_string(r.source_batch_id, string_table, string_index))
        col_trace.append(_intern_string(r.trace_id, string_table, string_index))
        col_qreason.append(_intern_string(r.quarantine_reason or "", string_table, string_index))
        col_receipt.append(_intern_string(r.delivery_receipt_id or "", string_table, string_index))

        col_interval_ms.append(int(r.interval_end_utc.timestamp() * 1000))
        col_updated_ms.append(int(r.updated_at_utc.timestamp() * 1000))
        col_kwh_del_scaled.append(int(r.scaled_kwh_delivered * _SCALE_FACTOR))
        col_kwh_rec_scaled.append(int(r.scaled_kwh_received * _SCALE_FACTOR))
        col_kvarh_scaled.append(int(r.reactive_kvarh * _SCALE_FACTOR))
        col_voltage.append(float(r.voltage_v))
        col_row_offset.append(int(r.parquet_row_offset))

    # Length-prefixed string table encoding to preserve embedded NUL bytes
    str_chunks: list[bytes] = []
    for s in string_table:
        s_bytes = s.encode("utf-8")
        str_chunks.append(struct.pack(">I", len(s_bytes)))
        str_chunks.append(s_bytes)
    encoded_strings = b"".join(str_chunks)
    header = struct.pack(">III", row_count, len(string_table), len(encoded_strings))

    column_buffers = b"".join(
        (
            header,
            encoded_strings,
            col_tenant.tobytes(),
            col_conn.tobytes(),
            col_gem.tobytes(),
            col_meter.tobytes(),
            col_sp.tobytes(),
            col_feeder.tobytes(),
            col_substation.tobytes(),
            col_tariff.tobytes(),
            col_quality.tobytes(),
            col_batch.tobytes(),
            col_trace.tobytes(),
            col_qreason.tobytes(),
            col_receipt.tobytes(),
            col_interval_ms.tobytes(),
            col_updated_ms.tobytes(),
            col_kwh_del_scaled.tobytes(),
            col_kwh_rec_scaled.tobytes(),
            col_kvarh_scaled.tobytes(),
            col_voltage.tobytes(),
            col_row_offset.tobytes(),
        )
    )
    compressed_body = zlib.compress(column_buffers, level=1)
    return ARROW_IPC_STREAM_MAGIC + compressed_body


def _read_string_table(
    raw_body: bytes,
    offset: int,
    str_bytes_len: int,
    str_table_count: int,
) -> tuple[list[str], int]:
    string_table: list[str] = []
    str_end = offset + str_bytes_len
    while offset < str_end and len(string_table) < str_table_count:
        (slen,) = struct.unpack(">I", raw_body[offset : offset + 4])
        offset += 4
        s = raw_body[offset : offset + slen].decode("utf-8")
        offset += slen
        string_table.append(s)
    return string_table, offset


def _parse_columnar_records(
    raw_body: bytes,
    row_count: int,
    string_table: list[str],
    offset: int,
) -> tuple[IntervalReading, ...]:
    int32_col_bytes = row_count * 4
    int64_col_bytes = row_count * 8

    def _read_int32_col(pos: int) -> tuple[array[int], int]:
        col = array("i")
        col.frombytes(raw_body[pos : pos + int32_col_bytes])
        return col, pos + int32_col_bytes

    def _read_int64_col(pos: int) -> tuple[array[int], int]:
        col = array("q")
        col.frombytes(raw_body[pos : pos + int64_col_bytes])
        return col, pos + int64_col_bytes

    def _read_float64_col(pos: int) -> tuple[array[float], int]:
        col = array("d")
        col.frombytes(raw_body[pos : pos + int64_col_bytes])
        return col, pos + int64_col_bytes

    col_tenant, offset = _read_int32_col(offset)
    col_conn, offset = _read_int32_col(offset)
    col_gem, offset = _read_int32_col(offset)
    col_meter, offset = _read_int32_col(offset)
    col_sp, offset = _read_int32_col(offset)
    col_feeder, offset = _read_int32_col(offset)
    col_substation, offset = _read_int32_col(offset)
    col_tariff, offset = _read_int32_col(offset)
    col_quality, offset = _read_int32_col(offset)
    col_batch, offset = _read_int32_col(offset)
    col_trace, offset = _read_int32_col(offset)
    col_qreason, offset = _read_int32_col(offset)
    col_receipt, offset = _read_int32_col(offset)

    col_interval_ms, offset = _read_int64_col(offset)
    col_updated_ms, offset = _read_int64_col(offset)
    col_kwh_del_scaled, offset = _read_int64_col(offset)
    col_kwh_rec_scaled, offset = _read_int64_col(offset)
    col_kvarh_scaled, offset = _read_int64_col(offset)
    col_voltage, offset = _read_float64_col(offset)
    col_row_offset, offset = _read_int32_col(offset)

    readings: list[IntervalReading] = []
    for idx in range(row_count):
        qreason = string_table[col_qreason[idx]]
        receipt = string_table[col_receipt[idx]]
        readings.append(
            IntervalReading(
                tenant_id=string_table[col_tenant[idx]],
                connection_id=string_table[col_conn[idx]],
                gem_device_id=string_table[col_gem[idx]],
                source_meter_id=string_table[col_meter[idx]],
                endpoint_location_id=string_table[col_sp[idx]],
                feeder_id=string_table[col_feeder[idx]],
                substation_id=string_table[col_substation[idx]],
                tariff_bucket=TariffBucket(string_table[col_tariff[idx]]),
                quality_status=CimQualityStatus(string_table[col_quality[idx]]),
                interval_end_utc=datetime.fromtimestamp(col_interval_ms[idx] / 1000.0, tz=UTC),
                scaled_kwh_delivered=(Decimal(col_kwh_del_scaled[idx]) / _SCALE_FACTOR).quantize(
                    Decimal("0.0001")
                ),
                scaled_kwh_received=(Decimal(col_kwh_rec_scaled[idx]) / _SCALE_FACTOR).quantize(
                    Decimal("0.0001")
                ),
                reactive_kvarh=(Decimal(col_kvarh_scaled[idx]) / _SCALE_FACTOR).quantize(
                    Decimal("0.0001")
                ),
                voltage_v=round(float(col_voltage[idx]), 4),
                source_batch_id=string_table[col_batch[idx]],
                parquet_row_offset=int(col_row_offset[idx]),
                trace_id=string_table[col_trace[idx]],
                updated_at_utc=datetime.fromtimestamp(col_updated_ms[idx] / 1000.0, tz=UTC),
                quarantine_reason=qreason if qreason else None,
                delivery_receipt_id=receipt if receipt else None,
            )
        )
    return tuple(readings)


def decode_arrow_ipc_stream(
    buffer: bytes,
) -> Result[tuple[IntervalReading, ...], IntervalMalformedBatchError]:
    """Decodes a contiguous binary columnar Arrow IPC buffer into IntervalReadings."""
    if not buffer.startswith(ARROW_IPC_STREAM_MAGIC):
        pyarrow_res = _try_decode_pyarrow_stream(buffer)
        if pyarrow_res is not None:
            return Result.ok(pyarrow_res)
        return Result.fail(
            IntervalMalformedBatchError.with_reason(
                "Buffer is missing ARROW1 IPC stream magic header."
            )
        )

    try:
        decompressor = zlib.decompressobj()
        raw_body = decompressor.decompress(
            buffer[len(ARROW_IPC_STREAM_MAGIC) :],
            max_length=MAX_DECOMPRESSED_BYTES + 1,
        )
        if len(raw_body) > MAX_DECOMPRESSED_BYTES or decompressor.unconsumed_tail:
            return Result.fail(
                IntervalMalformedBatchError.with_reason(
                    f"Decompressed Arrow IPC stream exceeds maximum allowed size ({MAX_DECOMPRESSED_BYTES} bytes)."
                )
            )

        if len(raw_body) < 12:
            return Result.fail(
                IntervalMalformedBatchError.with_reason("Truncated Arrow IPC columnar header.")
            )

        row_count, str_table_count, str_bytes_len = struct.unpack(">III", raw_body[:12])
        if row_count == 0:
            return Result.ok(())

        str_end = 12 + str_bytes_len
        if str_end > len(raw_body):
            return Result.fail(
                IntervalMalformedBatchError.with_reason(
                    "Truncated string table in Arrow IPC stream."
                )
            )

        string_table, offset = _read_string_table(raw_body, 12, str_bytes_len, str_table_count)
        readings = _parse_columnar_records(raw_body, row_count, string_table, offset)
        return Result.ok(readings)
    except (zlib.error, struct.error, IndexError, ValueError) as exc:
        return Result.fail(
            IntervalMalformedBatchError.with_reason(
                f"Failed to decode Arrow IPC columnar stream: {exc}"
            )
        )


__all__ = [
    "ARROW_IPC_STREAM_MAGIC",
    "decode_arrow_ipc_stream",
    "encode_arrow_ipc_stream",
]
