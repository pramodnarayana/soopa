"""Domain Value Objects for EDI Stage Explorer Filtering."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from seedwork.domain.types import JsonValue

from edi.domain.exceptions import EdiValidationError, Result

__all__ = [
    "ALLOWED_STAGE_FILTER_FIELDS",
    "EDI_JSON_UNSUPPORTED_FILTER_FIELDS",
    "FilterOperator",
    "StageFilterCriterion",
    "StageFilterTarget",
]


class FilterOperator(StrEnum):
    """Supported comparison operators for stage explorer queries."""

    EQ = "eq"
    NEQ = "neq"
    CONTAINS = "contains"
    IN = "in"


class StageFilterTarget(StrEnum):
    """Target stage ledger for explorer filter validation."""

    EDI_MESSAGE = "EDI_MESSAGE"
    EDI_JSON = "EDI_JSON"


ALLOWED_STAGE_FILTER_FIELDS: frozenset[str] = frozenset(
    {
        "trace_id",
        "original_trace_id",
        "parent_trace_id",
        "trading_partner_id",
        "direction",
        "status",
        "transaction_type",
        "error_code",
        "status_message",
        "sender_id",
        "receiver_id",
        "gs_sender_id",
        "gs_receiver_id",
        "format_standard",
        "connection_type",
        "business_metadata.shipment_id",
        "business_metadata.purchase_order_id",
        "business_metadata.po_number",
        "business_metadata.invoice_number",
        "business_metadata.load_number",
        "business_metadata.business_reference",
    }
)

EDI_JSON_UNSUPPORTED_FILTER_FIELDS: frozenset[str] = frozenset(
    {
        "sender_id",
        "receiver_id",
        "gs_sender_id",
        "gs_receiver_id",
    }
)


@dataclass(frozen=True, kw_only=True)
class StageFilterCriterion:
    """Strongly-typed filter criterion for EDI stage explorer queries."""

    field: str
    operator: FilterOperator = FilterOperator.EQ
    value: JsonValue

    @classmethod
    def create(
        cls,
        *,
        field: str,
        operator: FilterOperator | str = FilterOperator.EQ,
        value: JsonValue,
        target: StageFilterTarget,
    ) -> Result[StageFilterCriterion, EdiValidationError]:
        if field not in ALLOWED_STAGE_FILTER_FIELDS:
            return Result.fail(
                EdiValidationError.with_message(
                    f"Filter field '{field}' is not allowed.",
                    details={"field": field},
                )
            )

        if target == StageFilterTarget.EDI_JSON and field in EDI_JSON_UNSUPPORTED_FILTER_FIELDS:
            return Result.fail(
                EdiValidationError.with_message(
                    f"Filter field '{field}' is not supported for EdiJson records.",
                    details={"field": field, "target": target.value},
                )
            )

        if isinstance(operator, FilterOperator):
            resolved_op = operator
        else:
            valid_ops = {member.value: member for member in FilterOperator}
            if operator not in valid_ops:
                return Result.fail(
                    EdiValidationError.with_message(
                        f"Filter operator '{operator}' is not supported.",
                        details={"operator": operator},
                    )
                )
            resolved_op = valid_ops[operator]

        return Result.ok(cls(field=field, operator=resolved_op, value=value))

    @classmethod
    def validate_all(
        cls,
        raw_criteria: Sequence[tuple[str, FilterOperator | str, JsonValue]],
        *,
        target: StageFilterTarget,
    ) -> Result[tuple[StageFilterCriterion, ...], EdiValidationError]:
        validated: list[StageFilterCriterion] = []
        for field_name, operator, value in raw_criteria:
            res = cls.create(field=field_name, operator=operator, value=value, target=target)
            if res.is_err:
                return Result.fail(res.unwrap_err())
            validated.append(res.unwrap())
        return Result.ok(tuple(validated))
