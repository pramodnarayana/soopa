"""NormalizerStepHandler invoking Solution SDK TransformerSpec functions."""

from __future__ import annotations

import dataclasses
import json

import structlog
from ip.engine.domain.stitch.enums import StitchStepType
from ip.engine.domain.stitch.steps.pipeline_stage_steps import (
    NormalizerStepInput,
    NormalizerStepOutput,
)
from ip.sdk.registry import DomainFunctionRegistry, default_registry
from orchestration.domain.constants import EffectPolicy, StepFailureCode
from orchestration.domain.exceptions import Result
from orchestration.domain.failures import StepFailure, TerminalFailure
from orchestration.ports.inbound.step_handler_port import StepContext, StepHandlerPort
from seedwork.domain.types import JsonDict

logger = structlog.get_logger(__name__)


def _parse_raw_items(raw_payload: str) -> list[JsonDict]:
    """Safely extracts JSON dictionaries from a raw payload string."""
    try:
        parsed_json = json.loads(raw_payload)
        if isinstance(parsed_json, list):
            return [item for item in parsed_json if isinstance(item, dict)]
        if isinstance(parsed_json, dict):
            return [parsed_json]
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    return [{"raw": raw_payload}]


def _extract_record_dict(norm: object) -> list[JsonDict]:
    """Normalizes a single transformer result or collection into dictionary payloads."""
    results: list[JsonDict] = []
    if isinstance(norm, dict):
        results.append(norm)
    elif dataclasses.is_dataclass(norm) and not isinstance(norm, type):
        results.append(dataclasses.asdict(norm))
    elif isinstance(norm, (list, tuple)):
        for sub in norm:
            if isinstance(sub, dict):
                results.append(sub)
            elif dataclasses.is_dataclass(sub) and not isinstance(sub, type):
                results.append(dataclasses.asdict(sub))
    return results


class NormalizerStepHandler(StepHandlerPort[JsonDict, JsonDict]):
    """Invokes Solution SDK TransformerSpec functions to normalize raw payloads into canonical domain events."""

    def __init__(self, *, registry: DomainFunctionRegistry | None = None) -> None:
        self._registry = registry or default_registry

    @property
    def step_type(self) -> str:
        return StitchStepType.NORMALIZER.value

    @property
    def effect_policy(self) -> EffectPolicy:
        return EffectPolicy.PURE

    async def execute(
        self, context: StepContext, step_input: JsonDict
    ) -> Result[JsonDict, StepFailure]:
        bound = logger.bind(
            tenant_id=context.tenant_id,
            run_id=context.run_id,
            node_key=context.node_key,
        )
        bound.info("normalizer.received")

        parsed_res = NormalizerStepInput.from_payload(step_input)
        if parsed_res.is_err:
            detail = parsed_res.unwrap_err().message
            bound.error("normalizer.validation_failed", detail=detail)
            return Result.err(
                TerminalFailure(code=StepFailureCode.VALIDATION_REJECTED, detail=detail)
            )
        req = parsed_res.unwrap()

        descriptor = self._registry.get_transformer(req.app, req.entity)
        if descriptor is None:
            detail = f"No Solution Transformer registered for '{req.app}.{req.entity}'."
            bound.error("normalizer.transformer_missing", detail=detail)
            return Result.err(
                TerminalFailure(code=StepFailureCode.VALIDATION_REJECTED, detail=detail)
            )

        raw_items = _parse_raw_items(req.raw_payload)
        normalized_records: list[JsonDict] = []
        for item in raw_items:
            try:
                norm = descriptor.fn(item)
                normalized_records.extend(_extract_record_dict(norm))
            except (ValueError, TypeError, KeyError) as exc:
                detail = f"Transformer failed on record: {exc}"
                bound.error("normalizer.transform_error", detail=detail)
                return Result.err(
                    TerminalFailure(code=StepFailureCode.VALIDATION_REJECTED, detail=detail)
                )

        output = NormalizerStepOutput(
            app=req.app,
            entity=req.entity,
            connection_id=req.connection_id,
            normalized_records=tuple(normalized_records),
        )
        bound.info("normalizer.completed", normalized_count=len(normalized_records))
        return Result.ok(output.to_payload())


__all__ = ["NormalizerStepHandler"]
