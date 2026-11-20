"""Outbound port abstracting durable workflow execution, dispatch, and condition matching."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from seedwork.domain.types import JsonDict

from ip.engine.domain.exceptions import IpError, Result


@dataclass(frozen=True, kw_only=True)
class StartWorkflowRunCommand:
    """Command to start or deduplicate a durable workflow execution run."""

    tenant_id: str
    workflow_id: str
    workflow_version: int | None = None
    idempotency_key: str | None = None
    input_payload: JsonDict
    trace_id: str
    correlation_id: str | None = None
    parent_run_id: str | None = None
    parent_trace_id: str | None = None
    original_trace_id: str | None = None
    concurrency_key: str | None = None
    deduplicate_if_exists: bool = True
    now: datetime | None = None


@dataclass(frozen=True, kw_only=True)
class StartWorkflowRunResultDTO:
    """Summary outcome of starting a durable workflow run."""

    run_id: str
    was_deduplicated: bool


@dataclass(frozen=True, kw_only=True)
class SignalWorkflowEventCommand:
    """Command to signal an event to waiting workflow condition nodes."""

    tenant_id: str
    workflow_id: str | None = None
    event_key: str
    resource_hint: str | None = None
    payload: JsonDict
    now: datetime | None = None


@dataclass(frozen=True, kw_only=True)
class SignalWorkflowEventResultDTO:
    """Summary outcome of resolving event match conditions."""

    queued_step_ids: tuple[str, ...]


class WorkflowOrchestratorPort(Protocol):
    """Outbound port implemented by workflow engine adapters."""

    async def start_run(
        self, command: StartWorkflowRunCommand
    ) -> Result[StartWorkflowRunResultDTO, IpError]:
        """Start a new workflow run or deduplicate against an existing run."""
        ...

    async def signal_event(
        self, command: SignalWorkflowEventCommand
    ) -> Result[SignalWorkflowEventResultDTO, IpError]:
        """Signal an incoming event to resume paused/waiting workflow steps."""
        ...


__all__ = [
    "SignalWorkflowEventCommand",
    "SignalWorkflowEventResultDTO",
    "StartWorkflowRunCommand",
    "StartWorkflowRunResultDTO",
    "WorkflowOrchestratorPort",
]
