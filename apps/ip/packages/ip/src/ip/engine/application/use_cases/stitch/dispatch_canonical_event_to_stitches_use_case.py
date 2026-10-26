"""Use case bridging L3 Canonical Events to Stitch WorkflowRun triggers and WAIT_FOR_EVENT signals."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from observability import ObservabilityProvider
from orchestration.application.use_cases import (
    ResolveMatchConditionsCommand,
    ResolveMatchConditionsUseCase,
    StartRunCommand,
    StartRunUseCase,
)
from orchestration.domain.constants import ConditionKind
from orchestration.domain.exceptions import Result, WorkflowError
from seedwork.domain.types import JsonDict

from ip.engine.ports.outbound.stitch_catalog_registry_port import (
    StitchCatalogRegistryPort,
)

logger = ObservabilityProvider.logger(__name__)


@dataclass(frozen=True, kw_only=True)
class DispatchCanonicalEventToStitchesCommand:
    """Command emitted when an L3 Canonical Entity event arrives from the Normalization Engine."""

    tenant_id: str
    canonical_event_type: str
    event_id: str
    payload: JsonDict
    trace_id: str
    correlation_id: str | None = None
    now: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, kw_only=True)
class DispatchCanonicalEventResultDTO:
    """Summary of Stitch runs started and waiting steps signalled by a canonical event."""

    started_run_ids: tuple[str, ...]
    deduplicated_run_ids: tuple[str, ...]
    signalled_step_ids: tuple[str, ...]


class DispatchCanonicalEventToStitchesUseCase:
    """Routes an incoming L3 Canonical Event to matching StitchSubscriptions:
    - `is_trigger=True`: starts (or deduplicates) a durable `WorkflowRun` via `StartRunUseCase`.
    - `is_trigger=False`: evaluates `ConditionKind.CANONICAL_EVENT` matches via `ResolveMatchConditionsUseCase`.
    """

    def __init__(
        self,
        *,
        stitch_catalog: StitchCatalogRegistryPort,
        start_run_use_case: StartRunUseCase,
        resolve_matches_use_case: ResolveMatchConditionsUseCase,
    ) -> None:
        self._stitch_catalog = stitch_catalog
        self._start_run_use_case = start_run_use_case
        self._resolve_matches_use_case = resolve_matches_use_case

    async def execute(
        self, command: DispatchCanonicalEventToStitchesCommand
    ) -> Result[DispatchCanonicalEventResultDTO, WorkflowError]:
        subscriptions = self._stitch_catalog.list_subscriptions_for_event(
            tenant_id=command.tenant_id,
            canonical_event_type=command.canonical_event_type,
        )
        started_run_ids: list[str] = []
        deduplicated_run_ids: list[str] = []
        signalled_step_ids: list[str] = []

        for sub in subscriptions:
            if not sub.is_active:
                continue

            if sub.is_trigger:
                idempotency_key = sub.extract_idempotency_key(command.payload, command.event_id)
                concurrency_key = sub.extract_concurrency_key(command.payload)
                start_res = await self._start_run_use_case.execute(
                    StartRunCommand(
                        tenant_id=command.tenant_id,
                        workflow_id=sub.workflow_id,
                        workflow_version=sub.workflow_version,
                        idempotency_key=idempotency_key,
                        input_payload=command.payload,
                        trace_id=command.trace_id,
                        correlation_id=command.correlation_id,
                        concurrency_key=concurrency_key,
                        deduplicate_if_exists=True,
                        now=command.now,
                    )
                )
                if start_res.is_err:
                    return Result.err(start_res.unwrap_err())
                dto = start_res.unwrap()
                if dto.was_deduplicated:
                    deduplicated_run_ids.append(dto.run_id)
                else:
                    started_run_ids.append(dto.run_id)
            else:
                event_key = sub.condition_event_key or command.canonical_event_type
                resource_hint = sub.extract_resource_hint(command.payload)
                sig_res = await self._resolve_matches_use_case.execute(
                    ResolveMatchConditionsCommand(
                        tenant_id=command.tenant_id,
                        condition_kind=ConditionKind.CANONICAL_EVENT,
                        event_key=event_key,
                        resource_hint=resource_hint,
                        payload=command.payload,
                        now=command.now,
                    )
                )
                if sig_res.is_err:
                    return Result.err(sig_res.unwrap_err())
                signalled_step_ids.extend(sig_res.unwrap().queued_step_ids)

        logger.info(
            "canonical_event_dispatched_to_stitches",
            tenant_id=command.tenant_id,
            canonical_event_type=command.canonical_event_type,
            started_count=len(started_run_ids),
            deduplicated_count=len(deduplicated_run_ids),
            signalled_count=len(signalled_step_ids),
        )

        return Result.ok(
            DispatchCanonicalEventResultDTO(
                started_run_ids=tuple(started_run_ids),
                deduplicated_run_ids=tuple(deduplicated_run_ids),
                signalled_step_ids=tuple(signalled_step_ids),
            )
        )


__all__ = [
    "DispatchCanonicalEventResultDTO",
    "DispatchCanonicalEventToStitchesCommand",
    "DispatchCanonicalEventToStitchesUseCase",
]
