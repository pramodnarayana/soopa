"""UiFieldMapperStepHandler applying declarative Field Mapping Specs."""

from __future__ import annotations

import structlog
from ip.engine.domain.stitch.enums import StitchStepType
from ip.engine.domain.stitch.steps.pipeline_stage_steps import (
    UiFieldMapperStepInput,
    UiFieldMapperStepOutput,
)
from ip.engine.ports.outbound.mapping_spec_repository_port import (
    MappingSpecRepositoryPort,
)
from orchestration.domain.constants import EffectPolicy, StepFailureCode
from orchestration.domain.exceptions import Result
from orchestration.domain.failures import StepFailure, TerminalFailure
from orchestration.ports.inbound.step_handler_port import StepContext, StepHandlerPort
from seedwork.domain.types import JsonDict

logger = structlog.get_logger(__name__)


class UiFieldMapperStepHandler(StepHandlerPort[JsonDict, JsonDict]):
    """Applies declarative user-configured Field Mapping Specs to canonical records."""

    def __init__(
        self,
        *,
        mapping_spec_repository: MappingSpecRepositoryPort | None = None,
    ) -> None:
        self._mapping_spec_repo = mapping_spec_repository

    @property
    def step_type(self) -> str:
        return StitchStepType.UI_FIELD_MAPPER.value

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
        bound.info("ui_field_mapper.received")

        parsed_res = UiFieldMapperStepInput.from_payload(step_input)
        if parsed_res.is_err:
            detail = parsed_res.unwrap_err().message
            bound.error("ui_field_mapper.validation_failed", detail=detail)
            return Result.err(
                TerminalFailure(code=StepFailureCode.VALIDATION_REJECTED, detail=detail)
            )
        req = parsed_res.unwrap()

        projected: list[JsonDict] = []

        if req.mapping_spec_id and self._mapping_spec_repo is not None:
            spec = await self._mapping_spec_repo.get_by_id(
                tenant_id=context.tenant_id, mapping_spec_id=req.mapping_spec_id
            )
            if spec is not None:
                for rec in req.records:
                    projected.append(spec.project(rec))
            else:
                projected = list(req.records)
        else:
            projected = list(req.records)

        output = UiFieldMapperStepOutput(projected_records=tuple(projected))
        bound.info("ui_field_mapper.completed", projected_count=len(projected))
        return Result.ok(output.to_payload())


__all__ = ["UiFieldMapperStepHandler"]
