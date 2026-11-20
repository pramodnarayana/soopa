"""Adapter implementing WorkflowOrchestratorPort via the platform durable workflow engine."""

from __future__ import annotations

from datetime import UTC, datetime

from ip.engine.domain.exceptions import FailureDisposition, IpError, IpErrorCode, Result
from ip.engine.ports.outbound.workflow_orchestrator_port import (
    SignalWorkflowEventCommand,
    SignalWorkflowEventResultDTO,
    StartWorkflowRunCommand,
    StartWorkflowRunResultDTO,
    WorkflowOrchestratorPort,
)
from orchestration.application.use_cases import (
    ResolveMatchConditionsCommand,
    ResolveMatchConditionsUseCase,
    StartRunCommand,
    StartRunUseCase,
)
from orchestration.domain.constants import ConditionKind
from orchestration.ports.inbound.step_handler_port import (
    WorkflowDefinitionRegistryPort,
)


class DurableWorkflowOrchestratorAdapter(WorkflowOrchestratorPort):
    """Adapter bridging WorkflowOrchestratorPort to the platform durable workflow engine use cases."""

    def __init__(
        self,
        *,
        start_run_use_case: StartRunUseCase,
        resolve_matches_use_case: ResolveMatchConditionsUseCase,
        definition_registry: WorkflowDefinitionRegistryPort | None = None,
    ) -> None:
        self._start_run = start_run_use_case
        self._resolve_matches = resolve_matches_use_case
        self._definition_registry = definition_registry

    async def start_run(
        self, command: StartWorkflowRunCommand
    ) -> Result[StartWorkflowRunResultDTO, IpError]:
        effective_now = command.now or datetime.now(UTC)
        version = command.workflow_version
        if version is None:
            if self._definition_registry is not None:
                latest_res = self._definition_registry.get_latest(command.workflow_id)
                if latest_res.is_err:
                    return Result.err(
                        IpError(
                            code=IpErrorCode.INTERNAL_ERROR,
                            message=f"Durable workflow version resolution failed: {latest_res.unwrap_err().message}",
                            disposition=FailureDisposition.FAIL,
                        )
                    )
                version = latest_res.unwrap().version
            else:
                version = 1

        orch_cmd = StartRunCommand(
            tenant_id=command.tenant_id,
            workflow_id=command.workflow_id,
            workflow_version=version,
            idempotency_key=command.idempotency_key or f"{command.workflow_id}:{command.trace_id}",
            input_payload=command.input_payload,
            trace_id=command.trace_id,
            correlation_id=command.correlation_id,
            parent_run_id=command.parent_run_id,
            parent_trace_id=command.parent_trace_id,
            original_trace_id=command.original_trace_id,
            concurrency_key=command.concurrency_key,
            deduplicate_if_exists=command.deduplicate_if_exists,
            now=effective_now,
        )
        res = await self._start_run.execute(orch_cmd)
        if res.is_err:
            err = res.unwrap_err()
            return Result.err(
                IpError(
                    code=IpErrorCode.INTERNAL_ERROR,
                    message=f"Durable workflow start_run error: {err.message}",
                    disposition=FailureDisposition.FAIL,
                )
            )
        dto = res.unwrap()
        return Result.ok(
            StartWorkflowRunResultDTO(
                run_id=dto.run_id,
                was_deduplicated=dto.was_deduplicated,
            )
        )

    async def signal_event(
        self, command: SignalWorkflowEventCommand
    ) -> Result[SignalWorkflowEventResultDTO, IpError]:
        effective_now = command.now or datetime.now(UTC)
        orch_cmd = ResolveMatchConditionsCommand(
            tenant_id=command.tenant_id,
            workflow_id=command.workflow_id,
            condition_kind=ConditionKind.CANONICAL_EVENT,
            event_key=command.event_key,
            resource_hint=command.resource_hint,
            payload=command.payload,
            now=effective_now,
        )
        res = await self._resolve_matches.execute(orch_cmd)
        if res.is_err:
            err = res.unwrap_err()
            return Result.err(
                IpError(
                    code=IpErrorCode.INTERNAL_ERROR,
                    message=f"Durable workflow signal_event error: {err.message}",
                    disposition=FailureDisposition.FAIL,
                )
            )
        dto = res.unwrap()
        return Result.ok(
            SignalWorkflowEventResultDTO(
                queued_step_ids=tuple(dto.queued_step_ids),
            )
        )


__all__ = ["DurableWorkflowOrchestratorAdapter"]
