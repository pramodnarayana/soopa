"""Stateless seed-deterministic JSON Schema record synthesizer with jsf/Faker semantic providers."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Final

from ip.engine.domain.exceptions import IpError, IpErrorCode, Result
from ip.engine.ports.outbound.connector_port import RecordEnvelopeDTO
from ip.solutions.connectors.sandbox.universal.inference import infer_semantic_kind
from ip.solutions.connectors.sandbox.universal.spec import SimulatorStreamSpec
from seedwork.domain.types import JsonDict, JsonValue

_EPOCH_ANCHOR = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
_PATTERN_PREFIX_RE = re.compile(r"^\^?([A-Za-z0-9_-]+?)(?:\[0-9\]|\\d)\{(\d+)\}\$?$")
MAX_SYNTHESIS_DIGITS: Final[int] = 32
MAX_SYNTHESIS_ARRAY_ITEMS: Final[int] = 100

# jsf / Faker-inspired realistic enterprise value catalogs (deterministic via SHA-256 seed)
_FIRST_NAMES: tuple[str, ...] = (
    "Alice",
    "Marcus",
    "Elena",
    "David",
    "Priya",
    "Liam",
    "Sofia",
    "Noah",
    "Amara",
    "Lucas",
    "Chloe",
    "Ethan",
)
_LAST_NAMES: tuple[str, ...] = (
    "Mercier",
    "Vance",
    "Rostova",
    "Chen",
    "Patel",
    "O'Connor",
    "Alvarez",
    "Kowalski",
    "Takahashi",
    "Lindqvist",
    "Silva",
    "Brooks",
)
_COMPANIES: tuple[str, ...] = (
    "Apex Industrials",
    "Northstar Logistics",
    "Meridian Energy Corp",
    "Vertex Supply Chain",
    "Helios Manufacturing",
    "Pinnacle Freight Systems",
    "Solstice Global Retail",
    "Vanguard Grid Solutions",
    "Cobalt Cloud Enterprises",
    "Atlas Precision Dynamics",
)
_CITIES: tuple[str, ...] = (
    "Austin",
    "Chicago",
    "Seattle",
    "Boston",
    "Denver",
    "Atlanta",
    "Dallas",
    "San Jose",
    "Charlotte",
    "Portland",
)
_STATES: tuple[str, ...] = ("TX", "IL", "WA", "MA", "CO", "GA", "CA", "NC", "OR", "NY")
_COUNTRIES: tuple[str, ...] = ("US", "CA", "GB", "DE", "NL", "AU", "SG", "FR")
_CURRENCIES: tuple[str, ...] = ("USD", "EUR", "GBP", "CAD", "AUD")
_STREETS: tuple[str, ...] = (
    "742 Evergreen Terrace",
    "1200 Congress Ave",
    "450 Mission St",
    "880 Peachtree Rd",
    "310 Wacker Dr",
    "900 Stewart St",
    "225 Liberty St",
    "600 Boylston St",
)
_STATUSES: tuple[str, ...] = ("CREATED", "APPROVED", "IN_TRANSIT", "COMPLETED", "SETTLED")
_CATEGORIES: tuple[str, ...] = ("ENTERPRISE", "COMMERCIAL", "INDUSTRIAL", "EXPRESS", "STANDARD")


def _derive_seed_int(*parts: str | int) -> int:
    joined = "|".join(str(p) for p in parts)
    digest = hashlib.sha256(joined.encode("utf-8")).hexdigest()
    return int(digest[:16], 16)


def _parse_iso_cursor(cursor: str | None) -> datetime:
    if not cursor or not cursor.strip():
        return _EPOCH_ANCHOR
    cleaned = cursor.strip()
    if cleaned.endswith("Z"):
        cleaned = f"{cleaned[:-1]}+00:00"
    try:
        dt = datetime.fromisoformat(cleaned)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    except ValueError:
        return _EPOCH_ANCHOR


def _format_iso_utc(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _clamp_digit_width(raw_digits: object, *, default: int = 4) -> int:
    if isinstance(raw_digits, int) and not isinstance(raw_digits, bool):
        if raw_digits <= 0:
            return default
        return min(raw_digits, MAX_SYNTHESIS_DIGITS)
    if isinstance(raw_digits, str) and raw_digits.isdigit():
        if len(raw_digits) > 2:
            return MAX_SYNTHESIS_DIGITS
        parsed = int(raw_digits)
        return min(max(1, parsed), MAX_SYNTHESIS_DIGITS) if parsed > 0 else default
    return default


def _clamp_array_bounds(raw_min: object, raw_max: object) -> tuple[int, int]:
    if isinstance(raw_min, int) and not isinstance(raw_min, bool):
        min_items = min(max(0, raw_min), MAX_SYNTHESIS_ARRAY_ITEMS)
    else:
        min_items = 1

    if isinstance(raw_max, int) and not isinstance(raw_max, bool):
        max_items = min(max(min_items, raw_max), MAX_SYNTHESIS_ARRAY_ITEMS)
    else:
        max_items = min(max(min_items, 3), MAX_SYNTHESIS_ARRAY_ITEMS)
    return min_items, max_items


def _resolve_primary_key_prefix(
    spec: SimulatorStreamSpec,
    pk_prop: Mapping[str, JsonValue] | None,
) -> tuple[str, int]:
    if pk_prop is not None:
        raw_prefix = pk_prop.get("x_prefix")
        raw_digits = pk_prop.get("x_digits")
        if isinstance(raw_prefix, str) and raw_prefix:
            return raw_prefix, _clamp_digit_width(raw_digits, default=4)
        raw_pattern = pk_prop.get("pattern")
        if isinstance(raw_pattern, str):
            match = _PATTERN_PREFIX_RE.match(raw_pattern)
            if match is not None:
                pat_prefix, pat_digits = match.groups()
                return pat_prefix, _clamp_digit_width(pat_digits, default=4)

    fallback = re.sub(r"[^A-Za-z0-9]", "", spec.stream_name)[:3].upper() or "REC"
    return f"{fallback}-", 6


def _synthesize_primary_key(
    spec: SimulatorStreamSpec,
    pk_prop: Mapping[str, JsonValue] | None,
    seq_index: int,
) -> str:
    prefix, digits = _resolve_primary_key_prefix(spec, pk_prop)
    return f"{prefix}{seq_index:0{digits}d}"


def _extract_seq_num_from_record_id(
    spec: SimulatorStreamSpec,
    pk_prop: Mapping[str, JsonValue] | None,
    record_id: str,
) -> int | None:
    prefix, _ = _resolve_primary_key_prefix(spec, pk_prop)
    if not record_id.startswith(prefix):
        return None
    suffix = record_id[len(prefix) :]
    if not suffix or len(suffix) > 64 or not suffix.isdigit():
        return None
    seq_num = int(suffix)
    return seq_num if seq_num >= 1 else None


_SEMANTIC_CATALOG_MAP: dict[str, tuple[str, ...]] = {
    "first_name": _FIRST_NAMES,
    "last_name": _LAST_NAMES,
    "company": _COMPANIES,
    "city": _CITIES,
    "state": _STATES,
    "country": _COUNTRIES,
    "address": _STREETS,
    "currency": _CURRENCIES,
    "status": _STATUSES,
    "category": _CATEGORIES,
}


def _synthesize_semantic_string(semantic_kind: str, field_seed: int) -> str:
    catalog = _SEMANTIC_CATALOG_MAP.get(semantic_kind)
    if catalog is not None:
        return catalog[field_seed % len(catalog)]
    if semantic_kind == "full_name":
        first = _FIRST_NAMES[field_seed % len(_FIRST_NAMES)]
        last = _LAST_NAMES[(field_seed >> 4) % len(_LAST_NAMES)]
        return f"{first} {last}"
    if semantic_kind == "email":
        first = _FIRST_NAMES[field_seed % len(_FIRST_NAMES)].lower()
        last = _LAST_NAMES[(field_seed >> 4) % len(_LAST_NAMES)].lower().replace("'", "")
        return f"{first}.{last}{(field_seed % 90) + 10}@example.org"
    if semantic_kind == "phone":
        area = 200 + (field_seed % 700)
        line = 1000 + ((field_seed >> 8) % 9000)
        return f"+1-{area}-555-{line:04d}"
    if semantic_kind == "postal_code":
        return f"{10000 + (field_seed % 89999)}"
    if semantic_kind == "sku":
        return f"SKU-{(field_seed % 90000) + 10000}"
    return f"val_{(field_seed % 9000) + 1000}"


def _synthesize_formatted_string(
    field_name: str,
    fmt: str,
    field_seed: int,
    record_ts: datetime,
) -> str | None:
    if fmt == "date-time":
        return _format_iso_utc(record_ts)
    if fmt == "date":
        return record_ts.astimezone(UTC).strftime("%Y-%m-%d")
    if fmt == "uuid":
        hex_str = hashlib.sha256(f"uuid|{field_seed}".encode()).hexdigest()[:32]
        return f"{hex_str[:8]}-{hex_str[8:12]}-4{hex_str[13:16]}-a{hex_str[17:20]}-{hex_str[20:32]}"
    if fmt == "email":
        return _synthesize_semantic_string("email", field_seed)
    if fmt == "uri":
        return f"https://example.org/{field_name}/{(field_seed % 9000) + 1000}"
    return None


def _synthesize_prefixed_or_pattern_string(
    prop_schema: Mapping[str, JsonValue],
    field_seed: int,
) -> str | None:
    raw_prefix = prop_schema.get("x_prefix")
    if isinstance(raw_prefix, str) and raw_prefix:
        digits = _clamp_digit_width(prop_schema.get("x_digits"), default=4)
        span = max(1, (10**digits) - 1)
        num = (field_seed % span) + 1
        return f"{raw_prefix}{num:0{digits}d}"

    raw_pattern = prop_schema.get("pattern")
    if isinstance(raw_pattern, str):
        match = _PATTERN_PREFIX_RE.match(raw_pattern)
        if match is not None:
            pat_prefix, pat_digits = match.groups()
            d_len = _clamp_digit_width(pat_digits, default=4)
            span = max(1, (10**d_len) - 1)
            num = (field_seed % span) + 1
            return f"{pat_prefix}{num:0{d_len}d}"
    return None


def _synthesize_string_value(
    field_name: str,
    prop_schema: Mapping[str, JsonValue],
    field_seed: int,
    record_ts: datetime,
) -> str:
    enum_vals = prop_schema.get("enum")
    if (
        isinstance(enum_vals, Sequence)
        and not isinstance(enum_vals, (str, bytes))
        and len(enum_vals) > 0
    ):
        return str(enum_vals[field_seed % len(enum_vals)])

    const_val = prop_schema.get("const")
    if isinstance(const_val, str):
        return const_val

    fmt = prop_schema.get("format")
    if isinstance(fmt, str):
        formatted = _synthesize_formatted_string(field_name, fmt, field_seed, record_ts)
        if formatted is not None:
            return formatted

    prefixed = _synthesize_prefixed_or_pattern_string(prop_schema, field_seed)
    if prefixed is not None:
        return prefixed

    raw_semantic = prop_schema.get("x_semantic")
    semantic = raw_semantic if isinstance(raw_semantic, str) else infer_semantic_kind(field_name)
    if semantic is not None:
        return _synthesize_semantic_string(semantic, field_seed)

    example = prop_schema.get("example")
    if isinstance(example, str) and example.strip():
        if example.isupper() and example.replace("_", "").isalpha():
            candidates = (example, "PENDING", "ACTIVE", "COMPLETED")
            return candidates[field_seed % len(candidates)]
        return f"{example}_{(field_seed % 900) + 100}"

    return f"{field_name}_{(field_seed % 9000) + 1000}"


def _synthesize_field_value(
    field_name: str,
    prop_schema: Mapping[str, JsonValue],
    field_seed: int,
    record_ts: datetime,
    *,
    inject_spike: bool = False,
) -> JsonValue:
    raw_type = prop_schema.get("type")
    prop_type = str(raw_type).lower() if isinstance(raw_type, str) else "string"

    if prop_type == "boolean":
        return (field_seed % 2) == 0

    if prop_type == "integer":
        raw_min = prop_schema.get("minimum")
        raw_max = prop_schema.get("maximum")
        low = int(raw_min) if isinstance(raw_min, (int, float)) else 1
        high = int(raw_max) if isinstance(raw_max, (int, float)) else max(low + 100, 1000)
        span = max(1, high - low + 1)
        val = low + (field_seed % span)
        return val * 25 if inject_spike else val

    if prop_type == "number":
        raw_min = prop_schema.get("minimum")
        raw_max = prop_schema.get("maximum")
        low_f = float(raw_min) if isinstance(raw_min, (int, float)) else 10.0
        high_f = float(raw_max) if isinstance(raw_max, (int, float)) else max(low_f + 100.0, 1000.0)
        fraction = (field_seed % 10_000) / 10_000.0
        val_f = round(low_f + (high_f - low_f) * fraction, 2)
        return round(val_f * 25.0, 2) if inject_spike else val_f

    if prop_type == "object":
        nested_props = prop_schema.get("properties")
        if not isinstance(nested_props, Mapping):
            return {}
        nested_obj: dict[str, JsonValue] = {}
        for k, v in nested_props.items():
            sub_schema = v if isinstance(v, Mapping) else {"type": "string"}
            sub_seed = _derive_seed_int(field_seed, str(k))
            nested_obj[str(k)] = _synthesize_field_value(str(k), sub_schema, sub_seed, record_ts)
        return nested_obj

    if prop_type == "array":
        items_schema = prop_schema.get("items")
        item_def = items_schema if isinstance(items_schema, Mapping) else {"type": "string"}
        min_items, max_items = _clamp_array_bounds(
            prop_schema.get("minItems"),
            prop_schema.get("maxItems"),
        )
        count = min_items + (field_seed % max(1, max_items - min_items + 1))
        return [
            _synthesize_field_value(
                f"{field_name}_{idx}",
                item_def,
                _derive_seed_int(field_seed, idx),
                record_ts,
            )
            for idx in range(count)
        ]

    return _synthesize_string_value(field_name, prop_schema, field_seed, record_ts)


def _build_record_payload(
    spec: SimulatorStreamSpec,
    props: Mapping[str, JsonValue],
    pk_prop_map: Mapping[str, JsonValue] | None,
    seq_num: int,
    rec_seed: int,
    record_dt: datetime,
    iso_ts: str,
    *,
    inject_spike: bool,
    inject_violation: bool,
) -> tuple[str, dict[str, JsonValue]]:
    pk_value = _synthesize_primary_key(spec, pk_prop_map, seq_num)
    payload: dict[str, JsonValue] = {}
    for prop_name, prop_def in props.items():
        name_str = str(prop_name)
        if name_str == spec.primary_key_field:
            payload[name_str] = pk_value
            continue
        if name_str == spec.cursor_field:
            payload[name_str] = iso_ts
            continue
        prop_map = prop_def if isinstance(prop_def, Mapping) else {"type": "string"}
        f_seed = _derive_seed_int(rec_seed, name_str)
        payload[name_str] = _synthesize_field_value(
            name_str,
            prop_map,
            f_seed,
            record_dt,
            inject_spike=inject_spike,
        )

    payload.setdefault(spec.primary_key_field, pk_value)
    payload.setdefault(spec.cursor_field, iso_ts)

    if inject_violation:
        non_pk_keys = [k for k in payload if k not in (spec.primary_key_field, spec.cursor_field)]
        if non_pk_keys:
            payload[non_pk_keys[0]] = None

    return pk_value, payload


class JsonSchemaRecordSynthesizer:
    """Stateless, seed-deterministic record synthesizer driven by `SimulatorStreamSpec`."""

    def synthesize_batch(
        self,
        spec: SimulatorStreamSpec,
        *,
        seed: int,
        cursor: str | None = None,
        limit: int | None = None,
        sequence_offset: int | None = None,
    ) -> list[RecordEnvelopeDTO]:
        """Synthesizes a deterministic batch of records strictly newer than `cursor`."""
        target_count = max(1, min(limit or spec.records_per_pull, 5000))
        base_dt = _parse_iso_cursor(cursor)
        step_sec = max(1, spec.cursor_step_seconds)

        if sequence_offset is not None:
            start_seq = max(1, sequence_offset)
        else:
            elapsed_seconds = max(0, int((base_dt - _EPOCH_ANCHOR).total_seconds()))
            start_seq = (elapsed_seconds // step_sec) + 1

        raw_props = spec.json_schema.get("properties")
        props = raw_props if isinstance(raw_props, Mapping) else {}
        pk_prop = props.get(spec.primary_key_field)
        pk_prop_map = pk_prop if isinstance(pk_prop, Mapping) else None
        chaos = spec.chaos_policy

        records: list[RecordEnvelopeDTO] = []
        for idx in range(target_count):
            seq_num = start_seq + idx
            record_dt = base_dt + timedelta(seconds=step_sec * (idx + 1))
            iso_ts = _format_iso_utc(record_dt)
            rec_seed = _derive_seed_int(seed, spec.stream_name, seq_num)

            dup_roll = (rec_seed % 1000) / 10.0
            if (
                idx > 0
                and chaos.duplicate_rate_percent > 0.0
                and dup_roll < chaos.duplicate_rate_percent
            ):
                records.append(records[-1])
                continue

            spike_roll = ((rec_seed >> 8) % 1000) / 10.0
            inject_spike = (
                chaos.spike_anomaly_rate_percent > 0.0
                and spike_roll < chaos.spike_anomaly_rate_percent
            )
            violation_roll = ((rec_seed >> 16) % 1000) / 10.0
            inject_violation = (
                chaos.schema_violation_rate_percent > 0.0
                and violation_roll < chaos.schema_violation_rate_percent
            )

            pk_value, payload = _build_record_payload(
                spec,
                props,
                pk_prop_map,
                seq_num,
                rec_seed,
                record_dt,
                iso_ts,
                inject_spike=inject_spike,
                inject_violation=inject_violation,
            )

            records.append(
                RecordEnvelopeDTO(
                    stream_name=spec.stream_name,
                    record_id=pk_value,
                    data=payload,
                    emitted_at=iso_ts,
                    cursor_value=iso_ts,
                )
            )

        return records

    def synthesize_record_by_id(
        self,
        spec: SimulatorStreamSpec,
        *,
        seed: int,
        record_id: str,
    ) -> RecordEnvelopeDTO:
        """Deterministically reconstructs a single record by `record_id` (for Thin-Push Fetch-on-Notify).

        When `record_id` follows the stream's primary-key sequence format, derives the exact
        same seed, timestamp, and payload fields as `synthesize_batch` so pulled and fetched
        records for the same primary key are byte-for-byte identical.
        """
        raw_props = spec.json_schema.get("properties")
        props = raw_props if isinstance(raw_props, Mapping) else {}
        pk_prop = props.get(spec.primary_key_field)
        pk_prop_map = pk_prop if isinstance(pk_prop, Mapping) else None
        step_sec = max(1, spec.cursor_step_seconds)
        chaos = spec.chaos_policy

        seq_num = _extract_seq_num_from_record_id(spec, pk_prop_map, record_id)
        if seq_num is not None:
            rec_seed = _derive_seed_int(seed, spec.stream_name, seq_num)
            record_dt = _EPOCH_ANCHOR + timedelta(seconds=step_sec * seq_num)
        else:
            rec_seed = _derive_seed_int(seed, spec.stream_name, record_id)
            offset_seconds = ((rec_seed % 1_440) + 1) * step_sec
            record_dt = _EPOCH_ANCHOR + timedelta(seconds=offset_seconds)

        iso_ts = _format_iso_utc(record_dt)
        spike_roll = ((rec_seed >> 8) % 1000) / 10.0
        inject_spike = (
            chaos.spike_anomaly_rate_percent > 0.0 and spike_roll < chaos.spike_anomaly_rate_percent
        )
        violation_roll = ((rec_seed >> 16) % 1000) / 10.0
        inject_violation = (
            chaos.schema_violation_rate_percent > 0.0
            and violation_roll < chaos.schema_violation_rate_percent
        )

        _, payload = _build_record_payload(
            spec,
            props,
            pk_prop_map,
            seq_num or 1,
            rec_seed,
            record_dt,
            iso_ts,
            inject_spike=inject_spike,
            inject_violation=inject_violation,
        )
        payload[spec.primary_key_field] = record_id

        return RecordEnvelopeDTO(
            stream_name=spec.stream_name,
            record_id=record_id,
            data=payload,
            emitted_at=iso_ts,
            cursor_value=iso_ts,
        )

    def validate_payload_against_schema(
        self,
        spec: SimulatorStreamSpec,
        payload: JsonDict,
    ) -> Result[bool, IpError]:
        """Validates an outbound payload against `spec.json_schema` for L5 Destination verification."""
        raw_req = spec.json_schema.get("required")
        required_fields = (
            [str(r) for r in raw_req if isinstance(r, str)]
            if isinstance(raw_req, Sequence) and not isinstance(raw_req, (str, bytes))
            else []
        )
        missing = [req for req in required_fields if req not in payload or payload[req] is None]
        if missing:
            return Result.fail(
                IpError(
                    code=IpErrorCode.VALIDATION_FAILED,
                    message=f"Outbound payload for stream '{spec.stream_name}' is missing required fields: {', '.join(missing)}",
                    http_status=422,
                    details={"missing_fields": list(missing), "stream_name": spec.stream_name},
                )
            )
        return Result.ok(True)


__all__ = ["JsonSchemaRecordSynthesizer"]
