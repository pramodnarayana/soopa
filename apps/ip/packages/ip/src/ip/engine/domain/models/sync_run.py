"""SyncRun aggregate root representing a scheduled or manual pull synchronization execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import ClassVar

from seedwork.id_registry import DomainIdPrefix
from seedwork.models import AggregateRoot
from seedwork.utils import generate_id

from ip.engine.domain.enums import SyncRunKind, SyncRunStatus
from ip.engine.domain.events import (
    GenerationCompletedEvent,
    SyncRunCompletedEvent,
    SyncRunFailedEvent,
    SyncRunRequestedEvent,
    SyncRunStartedEvent,
)


@dataclass(kw_only=True, eq=False)
class SyncRun(AggregateRoot):
    """Aggregate root tracking execution of a stream pull sync run."""

    ID_PREFIX: ClassVar[str] = DomainIdPrefix.IP_SYNC_RUN.value

    id: str
    tenant_id: str
    connection_id: str
    stream: str
    kind: SyncRunKind
    generation_id: int
    status: SyncRunStatus = SyncRunStatus.PENDING
    start_checkpoint: str | None = None
    end_checkpoint: str | None = None
    pages_count: int = 0
    records_count: int = 0
    bytes_count: int = 0
    retry_count: int = 0
    error_code: str | None = None
    error_message: str | None = None
    trace_id: str
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @classmethod
    def create(
        cls,
        *,
        tenant_id: str,
        connection_id: str,
        stream: str,
        kind: SyncRunKind,
        generation_id: int = 1,
        start_checkpoint: str | None = None,
        trace_id: str | None = None,
    ) -> SyncRun:
        run_id = generate_id(cls.ID_PREFIX)
        resolved_trace_id = trace_id or generate_id(DomainIdPrefix.IP_TRACE.value)
        return cls(
            id=run_id,
            tenant_id=tenant_id,
            connection_id=connection_id,
            stream=stream,
            kind=kind,
            generation_id=generation_id,
            status=SyncRunStatus.PENDING,
            start_checkpoint=start_checkpoint,
            end_checkpoint=start_checkpoint,
            trace_id=resolved_trace_id,
        )

    @classmethod
    def request(
        cls,
        *,
        tenant_id: str,
        connection_id: str,
        stream: str,
        kind: SyncRunKind,
        generation_id: int = 1,
        start_checkpoint: str | None = None,
        trace_id: str | None = None,
        correlation_id: str | None = None,
    ) -> SyncRun:
        """Creates a PENDING SyncRun and records its SyncRunRequestedEvent for the outbox."""
        run = cls.create(
            tenant_id=tenant_id,
            connection_id=connection_id,
            stream=stream,
            kind=kind,
            generation_id=generation_id,
            start_checkpoint=start_checkpoint,
            trace_id=trace_id,
        )
        run.add_domain_event(
            SyncRunRequestedEvent(
                tenant_id=tenant_id,
                connection_id=connection_id,
                stream=stream,
                kind=kind.value,
                trace_id=run.trace_id,
                correlation_id=correlation_id,
            )
        )
        return run

    def start(self) -> None:
        """Transitions from PENDING to RUNNING, emitting SyncRunStartedEvent."""
        if self.status != SyncRunStatus.PENDING:
            raise ValueError(f"Cannot start sync run in state '{self.status}'. Must be PENDING.")
        self.status = SyncRunStatus.RUNNING
        self.started_at = datetime.now(UTC)
        self.add_domain_event(
            SyncRunStartedEvent(
                run_id=self.id,
                tenant_id=self.tenant_id,
                connection_id=self.connection_id,
                stream=self.stream,
                kind=self.kind.value,
                generation_id=self.generation_id,
                start_checkpoint=self.start_checkpoint,
                trace_id=self.trace_id,
            )
        )

    @property
    def pages_synced(self) -> int:
        return self.pages_count

    @property
    def records_synced(self) -> int:
        return self.records_count

    @property
    def bytes_synced(self) -> int:
        return self.bytes_count

    def record_page(
        self,
        *,
        records_in_page: int,
        bytes_size: int,
        next_checkpoint: str | None = None,
    ) -> None:
        """Records page metrics and advances the run's end_checkpoint."""
        if self.status != SyncRunStatus.RUNNING:
            raise ValueError(f"Cannot record page on sync run in state '{self.status}'.")
        self.pages_count += 1
        self.records_count += records_in_page
        self.bytes_count += bytes_size
        if next_checkpoint is not None:
            self.end_checkpoint = next_checkpoint

    def record_retry(self) -> None:
        """Records an intermediate retry attempt."""
        self.retry_count += 1

    def succeed(self, end_checkpoint: str | None = None) -> None:
        """Marks run as SUCCEEDED, emitting completion and generation events."""
        if self.status != SyncRunStatus.RUNNING:
            raise ValueError(f"Cannot succeed sync run in state '{self.status}'. Must be RUNNING.")
        if end_checkpoint is not None:
            self.end_checkpoint = end_checkpoint
        self.status = SyncRunStatus.SUCCEEDED
        self.finished_at = datetime.now(UTC)
        self.add_domain_event(
            SyncRunCompletedEvent(
                run_id=self.id,
                tenant_id=self.tenant_id,
                connection_id=self.connection_id,
                stream=self.stream,
                kind=self.kind.value,
                generation_id=self.generation_id,
                end_checkpoint=self.end_checkpoint,
                pages_count=self.pages_count,
                records_count=self.records_count,
                bytes_count=self.bytes_count,
                trace_id=self.trace_id,
            )
        )
        if self.kind == SyncRunKind.FULL_REFRESH:
            self.add_domain_event(
                GenerationCompletedEvent(
                    tenant_id=self.tenant_id,
                    connection_id=self.connection_id,
                    stream=self.stream,
                    generation_id=self.generation_id,
                    trace_id=self.trace_id,
                )
            )

    def fail(self, error_code: str, error_message: str) -> None:
        """Marks run as FAILED with error context, emitting SyncRunFailedEvent."""
        self.status = SyncRunStatus.FAILED
        self.error_code = error_code
        self.error_message = error_message
        self.finished_at = datetime.now(UTC)
        self.add_domain_event(
            SyncRunFailedEvent(
                run_id=self.id,
                tenant_id=self.tenant_id,
                connection_id=self.connection_id,
                stream=self.stream,
                kind=self.kind.value,
                generation_id=self.generation_id,
                error_code=error_code,
                error_message=error_message,
                trace_id=self.trace_id,
            )
        )

    def cancel(self, reason: str = "User cancelled") -> None:
        """Cancels an active or pending sync run."""
        self.status = SyncRunStatus.CANCELLED
        self.error_message = reason
        self.finished_at = datetime.now(UTC)
