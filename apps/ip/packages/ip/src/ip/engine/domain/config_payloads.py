"""Pure domain serializers producing canonical Dynamic Watch payloads for IP aggregates."""

from __future__ import annotations

from seedwork.domain.types import JsonDict, JsonValue

from ip.engine.domain.mapping.mapping_spec import MappingSpec
from ip.engine.domain.stitch.stitch import Stitch


def stitch_to_config_payload(stitch: Stitch) -> JsonDict:
    """Explicit Data Mapper from `Stitch` aggregate to canonical Dynamic Watch payload."""
    filter_conditions: JsonDict = {k: v for k, v in stitch.filter_conditions.items()}
    return {
        "id": stitch.id,
        "tenant_id": stitch.tenant_id,
        "canonical_event_type": stitch.canonical_event_type,
        "target_workflow_id": stitch.target_workflow_id,
        "name": stitch.name,
        "description": stitch.description,
        "mapping_spec_id": stitch.mapping_spec_id,
        "filter_conditions": filter_conditions,
        "is_active": stitch.is_active,
        "idempotency_key_field": stitch.idempotency_key_field,
        "concurrency_key_field": stitch.concurrency_key_field,
        "linked_stitch_id": stitch.linked_stitch_id,
    }


def mapping_spec_to_config_payload(spec: MappingSpec) -> JsonDict:
    """Explicit Data Mapper from `MappingSpec` aggregate to canonical Dynamic Watch payload."""
    rules_value: list[JsonValue] = [
        {
            "target_field": r.target_field,
            "rule_type": r.rule_type.value,
            "source_field": r.source_field,
            "constant_value": r.constant_value,
            "expression": r.expression,
        }
        for r in spec.rules
    ]
    return {
        "id": spec.id,
        "tenant_id": spec.tenant_id,
        "name": spec.name,
        "description": spec.description,
        "source_type": spec.source_type,
        "target_connection_id": spec.target_connection_id,
        "target_entity_name": spec.target_entity_name,
        "version": spec.version,
        "rules": rules_value,
        "is_active": spec.is_active,
    }


__all__ = ["mapping_spec_to_config_payload", "stitch_to_config_payload"]
