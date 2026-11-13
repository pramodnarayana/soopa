"""GenSON-inspired JSON Schema inference, blueprint validation, and StreamSchemaDTO extraction."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from ip.engine.domain.exceptions import IpError, IpErrorCode, Result
from ip.engine.ports.outbound.connector_port import StreamFieldDTO, StreamSchemaDTO
from ip.solutions.connectors.sandbox.universal.spec import (
    MAX_SAMPLE_BLUEPRINT_BYTES,
    SimulatorConnectionConfig,
    SimulatorStreamSpec,
)
from seedwork.domain.types import JsonDict, JsonValue

_ENTITY_NAME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]{0,127}$")
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


@dataclass(frozen=True)
class ValidatedEntityBlueprint:
    """Validated entity naming, normalized blueprint, inferred JSON Schema, and resolved key fields."""

    entity_name: str
    sample_blueprint: JsonValue
    inferred_json_schema: JsonDict
    primary_key_field: str
    cursor_field: str


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


def validate_entity_name(raw_name: str) -> Result[str, IpError]:
    """Validates a simulator entity name against `^[a-zA-Z][a-zA-Z0-9_-]{0,127}$`."""
    cleaned = raw_name.strip()
    if not _ENTITY_NAME_RE.match(cleaned):
        return Result.fail(
            IpError(
                code=IpErrorCode.VALIDATION_FAILED,
                message=(
                    f"Invalid simulator entity name '{raw_name}'. Must start with an ASCII letter "
                    f"and contain only letters, digits, underscores, or hyphens (max 128 chars)."
                ),
                http_status=422,
            )
        )
    return Result.ok(cleaned)


def _validate_blueprint_structure(sample_blueprint: JsonValue) -> Result[JsonValue, IpError]:
    if isinstance(sample_blueprint, Mapping):
        if len(sample_blueprint) == 0:
            return Result.fail(
                IpError(
                    code=IpErrorCode.VALIDATION_FAILED,
                    message="Simulator sample_blueprint JSON object cannot be empty.",
                    http_status=422,
                )
            )
        if _looks_like_json_schema(sample_blueprint):
            props = sample_blueprint.get("properties")
            if not isinstance(props, Mapping) or len(props) == 0:
                return Result.fail(
                    IpError(
                        code=IpErrorCode.VALIDATION_FAILED,
                        message="Simulator JSON Schema blueprint must define at least one property.",
                        http_status=422,
                    )
                )
        return Result.ok({str(k): v for k, v in sample_blueprint.items()})

    if isinstance(sample_blueprint, Sequence) and not isinstance(sample_blueprint, (str, bytes)):
        if len(sample_blueprint) == 0 or not all(
            isinstance(item, Mapping) and len(item) > 0 for item in sample_blueprint
        ):
            return Result.fail(
                IpError(
                    code=IpErrorCode.VALIDATION_FAILED,
                    message=(
                        "Simulator sample_blueprint array must contain at least one non-empty JSON object."
                    ),
                    http_status=422,
                )
            )
        normalized_list: list[JsonValue] = [
            {str(k): v for k, v in item.items()}
            for item in sample_blueprint
            if isinstance(item, Mapping)
        ]
        return Result.ok(normalized_list)

    return Result.fail(
        IpError(
            code=IpErrorCode.VALIDATION_FAILED,
            message=(
                "Simulator sample_blueprint must be a non-empty JSON object, JSON Schema, or array of JSON objects."
            ),
            http_status=422,
        )
    )


def build_validated_entity_blueprint(
    *,
    entity_name: str,
    sample_blueprint: JsonValue,
    primary_key_field: str | None = None,
    cursor_field: str | None = None,
) -> Result[ValidatedEntityBlueprint, IpError]:
    """Validates entity name & blueprint size/shape and computes the enriched server-side JSON Schema."""
    name_res = validate_entity_name(entity_name)
    if name_res.is_err:
        return Result.fail(name_res.unwrap_err())
    cleaned_name = name_res.unwrap()

    struct_res = _validate_blueprint_structure(sample_blueprint)
    if struct_res.is_err:
        return Result.fail(struct_res.unwrap_err())
    normalized_blueprint = struct_res.unwrap()

    serialized_bytes = len(json.dumps(normalized_blueprint).encode("utf-8"))
    if serialized_bytes > MAX_SAMPLE_BLUEPRINT_BYTES:
        return Result.fail(
            IpError(
                code=IpErrorCode.VALIDATION_FAILED,
                message=(
                    f"Simulator sample_blueprint exceeds maximum allowed size of "
                    f"{MAX_SAMPLE_BLUEPRINT_BYTES} bytes (received {serialized_bytes} bytes)."
                ),
                http_status=422,
            )
        )

    base_schema = infer_json_schema_from_sample(normalized_blueprint)
    enriched_schema, resolved_pk, resolved_cursor = _ensure_pk_and_cursor_in_schema(
        cleaned_name,
        base_schema,
        primary_key_field,
        cursor_field,
    )
    return Result.ok(
        ValidatedEntityBlueprint(
            entity_name=cleaned_name,
            sample_blueprint=normalized_blueprint,
            inferred_json_schema=enriched_schema,
            primary_key_field=resolved_pk,
            cursor_field=resolved_cursor,
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


def parse_simulator_connection_config(public_config: JsonDict) -> SimulatorConnectionConfig:
    """Extracts connection-level scalar parameters (`seed`, `records_per_pull`) from `public_config`."""
    return SimulatorConnectionConfig(
        seed=_extract_seed(public_config),
        default_records_per_pull=_extract_positive_int(public_config.get("records_per_pull"), 25),
    )


DEFAULT_SIMULATOR_TRANSFORMATIONS: Mapping[str, tuple[str, int]] = {
    "meter_readings": ("energy.ami_meter_reading", 2),
    "meter_reading": ("energy.ami_meter_reading", 2),
    "service_points": ("energy.ami_service_point", 1),
    "service_point": ("energy.ami_service_point", 1),
    "loads": ("tms.mercury_gate_load", 2),
    "load": ("tms.mercury_gate_load", 2),
    "carriers": ("tms.mercury_gate_carrier", 1),
    "carrier": ("tms.mercury_gate_carrier", 1),
}


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

    default_trans = DEFAULT_SIMULATOR_TRANSFORMATIONS.get(spec.stream_name)
    default_trans_id = default_trans[0] if default_trans is not None else None
    default_trans_ver = default_trans[1] if default_trans is not None else 1

    return StreamSchemaDTO(
        name=spec.stream_name,
        fields=tuple(fields),
        primary_key=(spec.primary_key_field,),
        cursor_field=spec.cursor_field,
        supported_sync_modes=("FULL_REFRESH", "INCREMENTAL"),
        default_transformation_id=default_trans_id,
        default_transformation_version=default_trans_ver,
    )


__all__ = [
    "DEFAULT_SIMULATOR_TRANSFORMATIONS",
    "ValidatedEntityBlueprint",
    "build_validated_entity_blueprint",
    "extract_stream_schema_dto",
    "infer_json_schema_from_sample",
    "infer_semantic_kind",
    "parse_simulator_connection_config",
    "validate_entity_name",
]
