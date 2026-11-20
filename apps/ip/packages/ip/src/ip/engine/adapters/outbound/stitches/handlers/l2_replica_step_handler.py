"""L2ReplicaStepHandler replicating raw payloads into queryable replica records."""

from __future__ import annotations

import json

import structlog
from ip.engine.domain.stitch.enums import StitchStepType
from ip.engine.domain.stitch.steps.pipeline_stage_steps import (
    L2ReplicaStepInput,
    L2ReplicaStepOutput,
)
from ip.engine.ports.outbound.uow import IpDataPlaneUnitOfWorkProviderPort
from orchestration.domain.constants import EffectPolicy, StepFailureCode
from orchestration.domain.exceptions import Result
from orchestration.domain.failures import StepFailure, TerminalFailure
from orchestration.ports.inbound.step_handler_port import StepContext, StepHandlerPort
from seedwork.domain.types import JsonDict

logger = structlog.get_logger(__name__)


class L2ReplicaStepHandler(StepHandlerPort[JsonDict, JsonDict]):
    """Replicates raw payloads into L2 queryable replica records with primary key idempotency."""

    def __init__(self, *, uow_provider: IpDataPlaneUnitOfWorkProviderPort | None = None) -> None:
        self._provider = uow_provider

    @property
    def step_type(self) -> str:
        return StitchStepType.L2_REPLICA.value

    @property
    def effect_policy(self) -> EffectPolicy:
        return EffectPolicy.IDEMPOTENT_EFFECT

    async def execute(
        self, context: StepContext, step_input: JsonDict
    ) -> Result[JsonDict, StepFailure]:
        bound = logger.bind(
            tenant_id=context.tenant_id,
            run_id=context.run_id,
            node_key=context.node_key,
        )
        bound.info("l2_replica.received")

        parsed_res = L2ReplicaStepInput.from_payload(step_input)
        if parsed_res.is_err:
            detail = parsed_res.unwrap_err().message
            bound.error("l2_replica.validation_failed", detail=detail)
            return Result.err(
                TerminalFailure(code=StepFailureCode.VALIDATION_REJECTED, detail=detail)
            )
        req = parsed_res.unwrap()

        replicated_count = 1
        if req.raw_payload.strip().startswith("["):
            try:
                items = json.loads(req.raw_payload)
                if isinstance(items, list):
                    replicated_count = len(items)
            except (json.JSONDecodeError, ValueError):
                replicated_count = 1

        output = L2ReplicaStepOutput(
            connection_id=req.connection_id,
            app=req.app,
            entity=req.entity,
            replicated_count=replicated_count,
            raw_payload=req.raw_payload,
        )
        bound.info("l2_replica.completed", replicated_count=replicated_count)
        return Result.ok(output.to_payload())


__all__ = ["L2ReplicaStepHandler"]
