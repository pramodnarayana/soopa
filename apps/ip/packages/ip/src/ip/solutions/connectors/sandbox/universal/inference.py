"""GenSON-inspired JSON Schema inference, multi-sample merging, and StreamSchemaDTO extraction."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence

from ip.engine.domain.exceptions import IpError, IpErrorCode, Result
from ip.engine.ports.outbound.connector_port import StreamFieldDTO, StreamSchemaDTO
from ip.solutions.connectors.sandbox.universal.chaos import SimulatorChaosPolicy
from ip.solutions.connectors.sandbox.universal.spec import (
    SimulatorManifest,
    SimulatorStreamSpec,
    StreamVelocityMode,
)
from seedwork.domain.types import JsonDict, JsonValue

_ISO_DATETIME_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?$"
)
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_ID_PREFIX_RE = re.compile(r"^([A-Za-z][A-Za-z0-9_-]*[-_])(\d+)$")

_JSON_SCHEMA_TO_STREAM_TYPE: Mapping[str, str] = {
    "string": "STRING",
    "integer": "INTEGER",
    "number": "NUMBER",
    "boolean": "BOOLEAN",
    "object": "OBJECT",
    "array": "ARRAY",
}

_SEMANTIC_FIELD_PATTERNS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("email", "e_mail"), "email"),
    (("first_name", "firstname", "given_name"), "first_name"),
    (("last_name", "lastname", "surname", "family_name"), "last_name"),
    (("customer_name", "contact_name", "full_name", "user_name", "person_name"), "full_name"),
    (("company", "vendor", "supplier", "merchant", "organization", "org_name"), "company"),
    (("phone", "mobile", "tel", "telephone"), "phone"),
    (("city", "town", "municipality"), "city"),
    (("state", "province", "region"), "state"),
    (("country", "country_code"), "country"),
    (("zip", "zipcode", "postal", "postal_code", "postcode"), "postal_code"),
    (("address", "street", "street_address", "line1"), "address"),
    (("currency", "currency_code"), "currency"),
    (("sku", "part_number", "item_code", "product_code"), "sku"),
    (("status", "lifecycle_state", "order_status", "payment_status"), "status"),
    (("department", "category", "segment", "tier"), "category"),
)


def infer_semantic_kind(field_name: str) -> str | None:
    """Infers a `jsf`/`Faker` semantic provider category from a property name."""
    norm = field_name.strip().lower()
    if not norm:
        return None
    for tokens, semantic_kind in _SEMANTIC_FIELD_PATTERNS:
        for token in tokens:
            if norm == token or norm.endswith(f"_{token}") or norm.startswith(f"{token}_"):
                return semantic_kind
    if norm == "name":
        return "full_name"
    return None


def _infer_string_property(value: str, field_name: str = "") -> JsonDict:
    trimmed = value.strip()
    semantic = infer_semantic_kind(field_name)
    if _ISO_DATETIME_RE.match(trimmed):
        return {"type": "string", "format": "date-time", "example": value}
    if _ISO_DATE_RE.match(trimmed):
        return {"type": "string", "format": "date", "example": value}
    if _UUID_RE.match(trimmed):
        return {"type": "string", "format": "uuid", "example": value}
    if _EMAIL_RE.match(trimmed) or semantic == "email":
        return {"type": "string", "format": "email", "example": value}
    if trimmed.startswith(("http://", "https://")):
        return {"type": "string", "format": "uri", "example": value}

    prefix_match = _ID_PREFIX_RE.match(trimmed)
    if prefix_match is not None:
        prefix, digits = prefix_match.groups()
        return {
            "type": "string",
            "x_prefix": prefix,
            "x_digits": len(digits),
            "example": value,
        }

    schema: dict[str, JsonValue] = {"type": "string", "example": value}
    if semantic is not None:
        schema["x_semantic"] = semantic
    return schema


def _infer_property_schema(value: JsonValue, field_name: str = "") -> JsonDict:
    if isinstance(value, bool):
        return {"type": "boolean", "example": value}
    if isinstance(value, int):
        low = max(0, int(value * 0.5)) if value >= 0 else int(value * 1.5)
        high = max(low + 10, int(value * 2.0) if value > 0 else 100)
        return {"type": "integer", "minimum": low, "maximum": high, "example": value}
    if isinstance(value, float):
        low_f = round(max(0.0, value * 0.5), 2) if value >= 0.0 else round(value * 1.5, 2)
        high_f = round(max(low_f + 10.0, value * 2.0 if value > 0.0 else 100.0), 2)
        return {"type": "number", "minimum": low_f, "maximum": high_f, "example": value}
    if isinstance(value, str):
        return _infer_string_property(value, field_name=field_name)
    if isinstance(value, Mapping):
        nested_props: dict[str, JsonValue] = {}
        nested_req: list[JsonValue] = []
        for k, v in value.items():
            key_str = str(k)
            nested_props[key_str] = _infer_property_schema(v, field_name=key_str)
            if v is not None:
                nested_req.append(key_str)
        return {
            "type": "object",
            "properties": nested_props,
            "required": nested_req,
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        item_schema: JsonDict = (
            _infer_property_schema(value[0], field_name=field_name)
            if len(value) > 0
            else {"type": "string"}
        )
        return {
            "type": "array",
            "items": item_schema,
            "minItems": 1,
            "maxItems": max(1, min(5, len(value))),
        }
    return {"type": "string", "nullable": True}


def _merge_single_property_across_samples(
    key: str,
    observed: list[JsonValue],
    *,
    is_required: bool,
) -> JsonDict:
    if not observed:
        return {"type": "string", "nullable": True}

    base_prop: JsonDict = dict(_infer_property_schema(observed[0], field_name=key))
    if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in observed):
        has_float = any(isinstance(v, float) for v in observed)
        nums = [float(v) for v in observed if isinstance(v, (int, float))]
        min_obs = min(nums)
        max_obs = max(nums)
        if has_float:
            low_f = round(min(min_obs * 0.8 if min_obs >= 0 else min_obs * 1.2, min_obs), 2)
            high_f = round(max(max_obs * 1.2 if max_obs > 0 else 100.0, low_f + 10.0), 2)
            base_prop = {
                "type": "number",
                "minimum": low_f,
                "maximum": high_f,
                "example": observed[0],
            }
        else:
            low_i = int(min(min_obs * 0.8 if min_obs >= 0 else min_obs * 1.2, min_obs))
            high_i = int(max(max_obs * 1.2 if max_obs > 0 else 100, low_i + 10))
            base_prop = {
                "type": "integer",
                "minimum": low_i,
                "maximum": high_i,
                "example": observed[0],
            }
    elif all(isinstance(v, str) for v in observed):
        str_vals = [str(v) for v in observed]
        distinct = list(dict.fromkeys(str_vals))
        is_categorical = len(distinct) < len(observed) or all(
            s.isupper() and s.replace("_", "").isalpha() for s in distinct
        )
        if (
            len(observed) >= 2
            and "format" not in base_prop
            and "x_prefix" not in base_prop
            and is_categorical
        ):
            base_prop["enum"] = list(distinct)

    if not is_required:
        base_prop["nullable"] = True
    return base_prop


def _merge_multi_sample_objects(samples: Sequence[Mapping[str, JsonValue]]) -> JsonDict:
    """GenSON-style multi-sample schema merger across an array of sample JSON objects."""
    total_samples = len(samples)
    if total_samples == 0:
        return {"type": "object", "properties": {}, "required": []}
    if total_samples == 1:
        return infer_json_schema_from_sample(dict(samples[0]))

    all_keys: list[str] = []
    seen_keys: set[str] = set()
    non_null_counts: dict[str, int] = {}
    values_by_key: dict[str, list[JsonValue]] = {}

    for sample in samples:
        for raw_k, val in sample.items():
            key = str(raw_k)
            if key not in seen_keys:
                seen_keys.add(key)
                all_keys.append(key)
            if val is not None:
                non_null_counts[key] = non_null_counts.get(key, 0) + 1
                values_by_key.setdefault(key, []).append(val)

    merged_props: dict[str, JsonValue] = {}
    required_fields: list[JsonValue] = []

    for key in all_keys:
        observed = values_by_key.get(key, [])
        is_required = non_null_counts.get(key, 0) == total_samples
        if is_required:
            required_fields.append(key)
        merged_props[key] = _merge_single_property_across_samples(
            key,
            observed,
            is_required=is_required,
        )

    return {
        "type": "object",
        "properties": merged_props,
        "required": required_fields,
    }


def _looks_like_json_schema(candidate: Mapping[str, JsonValue]) -> bool:
    if "$schema" in candidate:
        return True
    schema_type = candidate.get("type")
    props = candidate.get("properties")
    return schema_type == "object" and isinstance(props, Mapping)


def _normalize_existing_json_schema(sample: Mapping[str, JsonValue]) -> JsonDict:
    raw_props = sample.get("properties")
    props_dict: dict[str, JsonValue] = {}
    if isinstance(raw_props, Mapping):
        for k, v in raw_props.items():
            key_str = str(k)
            if isinstance(v, Mapping):
                prop_copy = dict(v)
                semantic = infer_semantic_kind(key_str)
                if (
                    semantic is not None
                    and prop_copy.get("type") == "string"
                    and "format" not in prop_copy
                    and "enum" not in prop_copy
                    and "pattern" not in prop_copy
                ):
                    prop_copy.setdefault("x_semantic", semantic)
                props_dict[key_str] = prop_copy
            else:
                props_dict[key_str] = v
    raw_req = sample.get("required")
    req_list: list[JsonValue] = (
        [str(r) for r in raw_req if isinstance(r, str)]
        if isinstance(raw_req, Sequence) and not isinstance(raw_req, (str, bytes))
        else list(props_dict.keys())
    )
    return {
        "type": "object",
        "properties": props_dict,
        "required": req_list,
    }


def infer_json_schema_from_sample(sample: JsonValue) -> JsonDict:
    """Infers or normalizes a JSON Schema dictionary from a sample JSON object, array of objects, or JSON Schema."""
    if isinstance(sample, str) and sample.strip():
        try:
            parsed = json.loads(sample)
        except json.JSONDecodeError:
            return {
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
            }
        return infer_json_schema_from_sample(parsed)

    if isinstance(sample, Sequence) and not isinstance(sample, (str, bytes)):
        obj_items = [item for item in sample if isinstance(item, Mapping)]
        if obj_items:
            return _merge_multi_sample_objects(obj_items)
        return {"type": "object", "properties": {}, "required": []}

    if isinstance(sample, Mapping):
        if _looks_like_json_schema(sample):
            return _normalize_existing_json_schema(sample)

        inferred_props: dict[str, JsonValue] = {}
        required_fields: list[JsonValue] = []
        for field_name, field_val in sample.items():
            key = str(field_name)
            inferred_props[key] = _infer_property_schema(field_val, field_name=key)
            if field_val is not None:
                required_fields.append(key)
        return {
            "type": "object",
            "properties": inferred_props,
            "required": required_fields,
        }

    return {"type": "object", "properties": {}, "required": []}


def _detect_primary_key(
    stream_name: str,
    properties: Mapping[str, JsonValue],
    explicit: str | None,
) -> str:
    if explicit and explicit.strip():
        return explicit.strip()
    if "id" in properties:
        return "id"
    singular = (
        stream_name[:-1] if stream_name.endswith("s") and len(stream_name) > 1 else stream_name
    )
    candidate = f"{singular}_id"
    if candidate in properties:
        return candidate
    for key in properties:
        if key.endswith("_id"):
            return key
    return next(iter(properties.keys()), "id")


def _detect_cursor_field(properties: Mapping[str, JsonValue], explicit: str | None) -> str:
    if explicit and explicit.strip():
        return explicit.strip()
    for candidate in ("updated_at", "timestamp", "modified_at", "created_at", "emitted_at"):
        if candidate in properties:
            return candidate
    return "updated_at"


def _extract_positive_int(raw: JsonValue | None, default: int, *, maximum: int = 5000) -> int:
    if isinstance(raw, int) and not isinstance(raw, bool):
        return max(1, min(maximum, raw))
    if isinstance(raw, float):
        return max(1, min(maximum, int(raw)))
    if isinstance(raw, str) and raw.strip():
        try:
            return max(1, min(maximum, int(raw.strip())))
        except ValueError:
            return default
    return default


def _ensure_pk_and_cursor_in_schema(
    cleaned_name: str,
    schema: JsonDict,
    explicit_pk: str | None,
    explicit_cursor: str | None,
) -> tuple[JsonDict, str, str]:
    props = schema.get("properties")
    props_map = props if isinstance(props, Mapping) else {}
    raw_req = schema.get("required")
    existing_req = (
        [str(r) for r in raw_req if isinstance(r, str)]
        if isinstance(raw_req, Sequence) and not isinstance(raw_req, (str, bytes))
        else list(props_map.keys())
    )
    pk_field = _detect_primary_key(cleaned_name, props_map, explicit_pk)
    cursor_field = _detect_cursor_field(props_map, explicit_cursor)

    mutable_props: dict[str, JsonValue] = dict(props_map)
    if pk_field not in mutable_props:
        prefix = cleaned_name[:3].upper()
        mutable_props[pk_field] = {"type": "string", "x_prefix": f"{prefix}-", "x_digits": 6}
        existing_req.append(pk_field)
    if cursor_field not in mutable_props:
        mutable_props[cursor_field] = {"type": "string", "format": "date-time"}
        existing_req.append(cursor_field)

    enriched_schema: JsonDict = {
        "type": "object",
        "properties": mutable_props,
        "required": list(dict.fromkeys(existing_req)),
    }
    return enriched_schema, pk_field, cursor_field


def _parse_wrapped_stream_spec(
    cleaned_name: str,
    raw_spec: Mapping[str, JsonValue],
    default_records_per_pull: int,
) -> Result[SimulatorStreamSpec, IpError]:
    raw_schema_source = raw_spec.get("json_schema") or raw_spec.get("sample_json") or {}
    if isinstance(raw_schema_source, str) and raw_schema_source.strip():
        try:
            raw_schema_source = json.loads(raw_schema_source)
        except json.JSONDecodeError as exc:
            return Result.fail(
                IpError(
                    code=IpErrorCode.MANIFEST_PARSE_ERROR,
                    message=f"Malformed JSON schema/sample in entity '{cleaned_name}': {exc.msg}",
                    http_status=422,
                )
            )
    base_schema = infer_json_schema_from_sample(raw_schema_source)
    explicit_pk = raw_spec.get("primary_key_field")
    explicit_cursor = raw_spec.get("cursor_field")
    schema, pk_field, cursor_field = _ensure_pk_and_cursor_in_schema(
        cleaned_name,
        base_schema,
        explicit_pk if isinstance(explicit_pk, str) else None,
        explicit_cursor if isinstance(explicit_cursor, str) else None,
    )
    raw_velocity = raw_spec.get("velocity_mode")
    velocity_mode = (
        StreamVelocityMode(raw_velocity)
        if isinstance(raw_velocity, str) and raw_velocity in StreamVelocityMode._value2member_map_
        else StreamVelocityMode.ENTITY_TRANSACTIONAL
    )
    records_per_pull = _extract_positive_int(
        raw_spec.get("records_per_pull"), default_records_per_pull
    )
    cursor_step_seconds = _extract_positive_int(
        raw_spec.get("cursor_step_seconds"), 60, maximum=86400
    )
    raw_chaos = raw_spec.get("chaos_policy")
    chaos_policy = SimulatorChaosPolicy.from_mapping(
        raw_chaos if isinstance(raw_chaos, Mapping) else None
    )
    return Result.ok(
        SimulatorStreamSpec(
            stream_name=cleaned_name,
            json_schema=schema,
            primary_key_field=pk_field,
            cursor_field=cursor_field,
            velocity_mode=velocity_mode,
            records_per_pull=records_per_pull,
            cursor_step_seconds=cursor_step_seconds,
            chaos_policy=chaos_policy,
        )
    )


def _parse_single_stream_spec(
    stream_name: str,
    raw_spec: JsonValue,
    default_records_per_pull: int,
) -> Result[SimulatorStreamSpec, IpError]:
    cleaned_name = stream_name.strip()
    if not cleaned_name:
        return Result.fail(
            IpError(
                code=IpErrorCode.MANIFEST_PARSE_ERROR,
                message="Simulator entity stream_name cannot be empty.",
                http_status=422,
            )
        )

    if isinstance(raw_spec, str) and raw_spec.strip():
        try:
            raw_spec = json.loads(raw_spec)
        except json.JSONDecodeError as exc:
            return Result.fail(
                IpError(
                    code=IpErrorCode.MANIFEST_PARSE_ERROR,
                    message=f"Invalid JSON provided for entity '{cleaned_name}': {exc.msg}",
                    http_status=422,
                )
            )

    if isinstance(raw_spec, Mapping):
        wrapper_keys = (
            "json_schema",
            "sample_json",
            "primary_key_field",
            "cursor_field",
            "records_per_pull",
        )
        if any(k in raw_spec for k in wrapper_keys):
            return _parse_wrapped_stream_spec(cleaned_name, raw_spec, default_records_per_pull)

    base_schema = infer_json_schema_from_sample(raw_spec)
    schema, pk_field, cursor_field = _ensure_pk_and_cursor_in_schema(
        cleaned_name,
        base_schema,
        None,
        None,
    )
    return Result.ok(
        SimulatorStreamSpec(
            stream_name=cleaned_name,
            json_schema=schema,
            primary_key_field=pk_field,
            cursor_field=cursor_field,
            records_per_pull=default_records_per_pull,
        )
    )


def _extract_seed(public_config: JsonDict) -> int:
    raw_seed = public_config.get("seed")
    if isinstance(raw_seed, int) and not isinstance(raw_seed, bool):
        return raw_seed
    if isinstance(raw_seed, str) and raw_seed.strip():
        try:
            return int(raw_seed.strip())
        except ValueError:
            return int(hashlib.sha256(raw_seed.strip().encode("utf-8")).hexdigest()[:8], 16)
    return 42


def _parse_streams_sequence(
    raw_streams: Sequence[JsonValue],
    default_records_per_pull: int,
) -> Result[dict[str, SimulatorStreamSpec], IpError]:
    parsed_streams: dict[str, SimulatorStreamSpec] = {}
    for item in raw_streams:
        if not isinstance(item, Mapping):
            continue
        raw_name = item.get("stream_name") or item.get("name")
        if not isinstance(raw_name, str) or not raw_name.strip():
            continue
        spec_res = _parse_single_stream_spec(raw_name, item, default_records_per_pull)
        if spec_res.is_err:
            return Result.fail(spec_res.unwrap_err())
        spec = spec_res.unwrap()
        parsed_streams[spec.stream_name] = spec
    return Result.ok(parsed_streams)


def parse_simulator_manifest(public_config: JsonDict) -> Result[SimulatorManifest, IpError]:
    """Parses `public_config` into a validated `SimulatorManifest`."""
    seed = _extract_seed(public_config)
    default_records_per_pull = _extract_positive_int(public_config.get("records_per_pull"), 25)
    raw_streams = public_config.get("streams")

    if not raw_streams:
        return Result.ok(SimulatorManifest(seed=seed, streams={}))

    if isinstance(raw_streams, str) and raw_streams.strip():
        try:
            raw_streams = json.loads(raw_streams)
        except json.JSONDecodeError as exc:
            return Result.fail(
                IpError(
                    code=IpErrorCode.MANIFEST_PARSE_ERROR,
                    message=f"Invalid JSON in 'streams' configuration: {exc.msg}",
                    http_status=422,
                )
            )

    if isinstance(raw_streams, Mapping):
        parsed_streams: dict[str, SimulatorStreamSpec] = {}
        for name, spec_val in raw_streams.items():
            spec_res = _parse_single_stream_spec(str(name), spec_val, default_records_per_pull)
            if spec_res.is_err:
                return Result.fail(spec_res.unwrap_err())
            spec = spec_res.unwrap()
            parsed_streams[spec.stream_name] = spec
        return Result.ok(SimulatorManifest(seed=seed, streams=parsed_streams))

    if isinstance(raw_streams, Sequence) and not isinstance(raw_streams, (str, bytes)):
        seq_res = _parse_streams_sequence(raw_streams, default_records_per_pull)
        if seq_res.is_err:
            return Result.fail(seq_res.unwrap_err())
        return Result.ok(SimulatorManifest(seed=seed, streams=seq_res.unwrap()))

    return Result.fail(
        IpError(
            code=IpErrorCode.MANIFEST_PARSE_ERROR,
            message="Simulator 'streams' configuration must be a JSON object or array.",
            http_status=422,
        )
    )


def extract_stream_schema_dto(spec: SimulatorStreamSpec) -> StreamSchemaDTO:
    """Translates a `SimulatorStreamSpec` into a `StreamSchemaDTO` for catalog discovery."""
    raw_props = spec.json_schema.get("properties")
    props = raw_props if isinstance(raw_props, Mapping) else {}
    raw_req = spec.json_schema.get("required")
    required_set = (
        {str(r) for r in raw_req if isinstance(r, str)}
        if isinstance(raw_req, Sequence) and not isinstance(raw_req, (str, bytes))
        else set()
    )

    fields: list[StreamFieldDTO] = []
    for field_name, field_def in props.items():
        name_str = str(field_name)
        raw_type = field_def.get("type") if isinstance(field_def, Mapping) else "string"
        type_key = str(raw_type).lower() if isinstance(raw_type, str) else "string"
        mapped_type = _JSON_SCHEMA_TO_STREAM_TYPE.get(type_key, "STRING")
        explicit_nullable = (
            bool(field_def.get("nullable")) if isinstance(field_def, Mapping) else False
        )
        is_nullable = (
            explicit_nullable or (name_str not in required_set)
        ) and name_str != spec.primary_key_field
        description = (
            str(field_def.get("description"))
            if isinstance(field_def, Mapping) and isinstance(field_def.get("description"), str)
            else None
        )
        fields.append(
            StreamFieldDTO(
                name=name_str,
                data_type=mapped_type,
                nullable=is_nullable,
                description=description,
            )
        )

    return StreamSchemaDTO(
        name=spec.stream_name,
        fields=tuple(fields),
        primary_key=(spec.primary_key_field,),
        cursor_field=spec.cursor_field,
        supported_sync_modes=("FULL_REFRESH", "INCREMENTAL"),
    )


__all__ = [
    "extract_stream_schema_dto",
    "infer_json_schema_from_sample",
    "infer_semantic_kind",
    "parse_simulator_manifest",
]
