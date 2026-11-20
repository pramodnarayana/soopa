"""Use case bridging L3 Canonical Events to Stitch WorkflowRun triggers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

import structlog
from seedwork.domain.types import JsonDict

from ip.engine.domain.exceptions import IpError, Result
from ip.engine.domain.stitch.stitch import Stitch
from ip.engine.ports.outbound.stitch_catalog_registry_port import (
    StitchCatalogRegistryPort,
)
from ip.engine.ports.outbound.uow import IpControlPlaneUnitOfWorkPort
from ip.engine.ports.outbound.workflow_orchestrator_port import (
    StartWorkflowRunCommand,
    WorkflowOrchestratorPort,
)

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, kw_only=True)
class DispatchCanonicalEventToStitchesCommand:
    """Command emitted when an L3 Canonical Entity event arrives from the Normalization Engine."""

    tenant_id: str
    canonical_event_type: str
    event_id: str
    payload: JsonDict
    trace_id: str
    correlation_id: str | None = None
    parent_trace_id: str | None = None
    original_trace_id: str | None = None
    now: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, kw_only=True)
class DispatchCanonicalEventResultDTO:
    """Summary of Stitch runs started by a canonical event."""

    started_run_ids: tuple[str, ...]
    deduplicated_run_ids: tuple[str, ...]
    signalled_step_ids: tuple[str, ...] = ()


class DispatchCanonicalEventToStitchesUseCase:
    """Routes an incoming L3 Canonical Event to matching Stitches and starts durable WorkflowRuns."""

    def __init__(
        self,
        *,
        stitch_catalog: StitchCatalogRegistryPort,
        orchestrator: WorkflowOrchestratorPort,
        control_plane_uow: IpControlPlaneUnitOfWorkPort | None = None,
    ) -> None:
        self._stitch_catalog = stitch_catalog
        self._orchestrator = orchestrator
        self._control_plane_uow = control_plane_uow

    async def _resolve_stitches_for_event(
        self,
        *,
        tenant_id: str,
        canonical_event_type: str,
    ) -> tuple[Stitch, ...]:
        if self._control_plane_uow is None:
            return tuple(
                self._stitch_catalog.list_stitches_for_event(
                    tenant_id=tenant_id,
                    canonical_event_type=canonical_event_type,
                )
            )
        merged: dict[str, Stitch] = {
            s.id: s
            for s in self._stitch_catalog.list_stitches(tenant_id=tenant_id)
            if s.canonical_event_type == canonical_event_type
        }
        async with self._control_plane_uow:
            db_stitches = await self._control_plane_uow.stitches.list_by_tenant(tenant_id=tenant_id)
            for stitch in db_stitches:
                if stitch.canonical_event_type == canonical_event_type:
                    merged[stitch.id] = stitch
                elif stitch.id in merged:
                    del merged[stitch.id]
        return tuple(s for s in merged.values() if s.is_active)

    async def execute(
        self, command: DispatchCanonicalEventToStitchesCommand
    ) -> Result[DispatchCanonicalEventResultDTO, IpError]:
        stitches = await self._resolve_stitches_for_event(
            tenant_id=command.tenant_id,
            canonical_event_type=command.canonical_event_type,
        )
        started_run_ids: list[str] = []
        deduplicated_run_ids: list[str] = []

        for stitch in stitches:
            if not stitch.is_active:
                continue
            if not stitch.matches_payload(command.payload):
                logger.info(
                    "stitch_event_filtered_out",
                    tenant_id=command.tenant_id,
                    stitch_id=stitch.id,
                    target_workflow_id=stitch.target_workflow_id,
                    canonical_event_type=command.canonical_event_type,
                )
                continue

            idempotency_key = (
                stitch.extract_idempotency_key(command.payload, command.event_id)
                if hasattr(stitch, "extract_idempotency_key")
                else f"{stitch.target_workflow_id}:{command.event_id}"
            )
            concurrency_key = (
                stitch.extract_concurrency_key(command.payload)
                if hasattr(stitch, "extract_concurrency_key")
                else None
            ) or command.correlation_id
            start_res = await self._orchestrator.start_run(
                StartWorkflowRunCommand(
                    tenant_id=command.tenant_id,
                    workflow_id=stitch.target_workflow_id,
                    idempotency_key=idempotency_key,
                    concurrency_key=concurrency_key,
                    input_payload=command.payload,
                    trace_id=command.trace_id,
                    correlation_id=command.correlation_id,
                    parent_trace_id=command.parent_trace_id,
                    original_trace_id=command.original_trace_id,
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

        logger.info(
            "canonical_event_dispatched_to_stitches",
            tenant_id=command.tenant_id,
            canonical_event_type=command.canonical_event_type,
            started_count=len(started_run_ids),
            deduplicated_count=len(deduplicated_run_ids),
        )

        return Result.ok(
            DispatchCanonicalEventResultDTO(
                started_run_ids=tuple(started_run_ids),
                deduplicated_run_ids=tuple(deduplicated_run_ids),
                signalled_step_ids=(),
            )
        )


__all__ = [
    "DispatchCanonicalEventResultDTO",
    "DispatchCanonicalEventToStitchesCommand",
    "DispatchCanonicalEventToStitchesUseCase",
]
