"""SliceRangeStepHandler decomposing date ranges into discrete chunk tasks."""

from __future__ import annotations

from datetime import timedelta

import structlog
from ip.engine.domain.stitch.enums import StitchStepType
from ip.engine.domain.stitch.steps.slice_range_steps import (
    SliceRangeStepInput,
    SliceRangeStepOutput,
    SliceTaskDTO,
)
from ip.engine.ports.outbound.connection_policy_repository_port import (
    ConnectionPolicyRepositoryPort,
)
from orchestration.domain.constants import EffectPolicy, StepFailureCode
from orchestration.domain.exceptions import Result
from orchestration.domain.failures import StepFailure, TerminalFailure
from orchestration.ports.inbound.step_handler_port import StepContext, StepHandlerPort
from seedwork.domain.types import JsonDict

logger = structlog.get_logger(__name__)


class SliceRangeStepHandler(StepHandlerPort[JsonDict, JsonDict]):
    """Pure domain-agnostic step handler decomposing date ranges into discrete chunk tasks
    with dynamic, heterogeneous connection policy resolution and guardrails.
    """

    MAX_DECOMPOSED_TASKS_PER_REQUEST: int = 500

    def __init__(
        self,
        *,
        policy_repository: ConnectionPolicyRepositoryPort | None = None,
    ) -> None:
        self._policy_repo = policy_repository

    @property
    def step_type(self) -> str:
        return StitchStepType.SLICE_RANGE.value

    @property
    def effect_policy(self) -> EffectPolicy:
        return EffectPolicy.PURE

    async def execute(
        self, context: StepContext, step_input: JsonDict
    ) -> Result[JsonDict, StepFailure]:
        bound = logger.bind(
            tenant_id=context.tenant_id,
            run_id=context.run_id,
            step_run_id=context.step_run_id,
            node_key=context.node_key,
        )
        bound.info("slice_range.received")

        parsed_res = SliceRangeStepInput.from_payload(step_input)
        if parsed_res.is_err:
            detail = parsed_res.unwrap_err().message
            bound.error("slice_range.validation_rejected", detail=detail)
            return Result.err(
                TerminalFailure(
                    code=StepFailureCode.VALIDATION_REJECTED,
                    detail=detail,
                )
            )
        req = parsed_res.unwrap()

        tasks: list[SliceTaskDTO] = []
        task_idx = 0

        # Slicing is performed independently per target connection to honor heterogeneous bandwidth policies
        for conn_id in req.target_connections:
            # 1. Resolve operational connection policy if repository is injected
            policy = None
            if self._policy_repo is not None:
                policy = await self._policy_repo.get_by_connection_id(
                    tenant_id=context.tenant_id,
                    connection_id=conn_id,
                )

            # 2. Enforce wildcard query constraints
            if policy is not None and not policy.supports_wildcard_queries:
                serials = (
                    req.filter_criteria.get("meter_serials")
                    or req.filter_criteria.get("entities")
                    or req.filter_criteria.get("device_ids")
                )
                if (
                    not serials
                    or serials == "*"
                    or (isinstance(serials, (list, tuple)) and len(serials) == 0)
                ):
                    detail = (
                        f"Connection '{conn_id}' policy forbids wildcard queries without "
                        f"explicit entity filters (e.g. meter_serials)."
                    )
                    bound.error(
                        "slice_range.wildcard_rejected",
                        connection_id=conn_id,
                        detail=detail,
                    )
                    return Result.err(
                        TerminalFailure(
                            code=StepFailureCode.VALIDATION_REJECTED,
                            detail=detail,
                        )
                    )

            # 3. Determine slice window limit (Tier 1: Policy, Tier 2: Public config/request)
            if policy is not None and policy.max_query_window_days > 0:
                delta = timedelta(days=policy.max_query_window_days)
            else:
                delta = (
                    timedelta(days=req.slice_size)
                    if req.slice_unit in ("DAY", "DAYS")
                    else timedelta(hours=req.slice_size)
                )

            # 4. Decompose date range for this connection
            current_start = req.start_date
            while current_start < req.end_date:
                current_end = min(current_start + delta, req.end_date)
                start_iso = current_start.isoformat()
                end_iso = current_end.isoformat()

                tasks.append(
                    SliceTaskDTO(
                        task_id=f"slice_{task_idx}_{conn_id}",
                        connection_id=conn_id,
                        slice_start=start_iso,
                        slice_end=end_iso,
                        filter_criteria=req.filter_criteria,
                        destination=req.destination,
                    )
                )
                task_idx += 1
                current_start = current_end

                # 5. Enforce explosion guardrail
                if len(tasks) > self.MAX_DECOMPOSED_TASKS_PER_REQUEST:
                    detail = (
                        f"Decomposed tasks ({len(tasks)}) exceeded maximum allowable "
                        f"limit ({self.MAX_DECOMPOSED_TASKS_PER_REQUEST})."
                    )
                    bound.error(
                        "slice_range.explosion_rejected", detail=detail, tasks_count=len(tasks)
                    )
                    return Result.err(
                        TerminalFailure(
                            code=StepFailureCode.VALIDATION_REJECTED,
                            detail=detail,
                        )
                    )

        bound.info(
            "slice_range.completed",
            total_slices=len(tasks),
            target_connections_count=len(req.target_connections),
        )
        return Result.ok(
            SliceRangeStepOutput(
                total_slices=len(tasks),
                tasks=tuple(tasks),
            ).to_payload()
        )


__all__ = ["SliceRangeStepHandler"]
