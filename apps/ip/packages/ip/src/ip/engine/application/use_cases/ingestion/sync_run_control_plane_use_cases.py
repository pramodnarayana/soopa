"""Control Plane use cases for triggering and inspecting pull sync runs and stream checkpoints."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import structlog

from ip.engine.domain.enums import ConnectionStatus, SyncRunKind
from ip.engine.domain.exceptions import (
    ActiveSyncRunAlreadyExistsError,
    ConnectionDeactivatedError,
    ConnectionNotFoundError,
    IpError,
    Result,
    SyncRunNotFoundError,
)
from ip.engine.domain.models.stream_state import ConnectionStreamState
from ip.engine.domain.models.sync_run import SyncRun
from ip.engine.ports.outbound.uow import IpControlPlaneUnitOfWorkPort

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class SyncRunSummaryDTO:
    """Pure boundary DTO representing a SyncRun aggregate."""

    run_id: str
    tenant_id: str
    connection_id: str
    stream_name: str
    kind: str
    generation_id: int
    status: str
    start_checkpoint: str | None
    end_checkpoint: str | None
    pages_count: int
    records_count: int
    bytes_count: int
    retry_count: int
    error_code: str | None
    error_message: str | None
    trace_id: str
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime


@dataclass(frozen=True)
class StreamStateSummaryDTO:
    """Pure boundary DTO representing a ConnectionStreamState checkpoint aggregate."""

    state_id: str
    tenant_id: str
    connection_id: str
    stream_name: str
    cursor_field: str | None
    cursor_value: str | None
    records_synced_count: int
    last_synced_at: datetime


@dataclass(frozen=True)
class TriggerSyncRunCommand:
    """Command to request an asynchronous pull synchronization run via the Control Plane outbox."""

    tenant_id: str
    connection_id: str
    stream_name: str
    forced_kind: SyncRunKind | None = None
    correlation_id: str | None = None


@dataclass(frozen=True)
class ListSyncRunsQuery:
    """Query to list recent SyncRuns for a connection."""

    tenant_id: str
    connection_id: str
    limit: int = 50


@dataclass(frozen=True)
class GetSyncRunQuery:
    """Query to retrieve a specific SyncRun by ID."""

    tenant_id: str
    connection_id: str
    run_id: str


@dataclass(frozen=True)
class ListStreamStatesQuery:
    """Query to list all stream state checkpoints for a connection."""

    tenant_id: str
    connection_id: str


@dataclass(frozen=True)
class ResetStreamCheckpointCommand:
    """Command to reset a stream's incremental checkpoint cursor to force full historical re-sync."""

    tenant_id: str
    connection_id: str
    stream_name: str


def _to_sync_run_dto(run: SyncRun) -> SyncRunSummaryDTO:
    return SyncRunSummaryDTO(
        run_id=run.id,
        tenant_id=run.tenant_id,
        connection_id=run.connection_id,
        stream_name=run.stream,
        kind=run.kind.value,
        generation_id=run.generation_id,
        status=run.status.value,
        start_checkpoint=run.start_checkpoint,
        end_checkpoint=run.end_checkpoint,
        pages_count=run.pages_count,
        records_count=run.records_count,
        bytes_count=run.bytes_count,
        retry_count=run.retry_count,
        error_code=run.error_code,
        error_message=run.error_message,
        trace_id=run.trace_id,
        started_at=run.started_at,
        finished_at=run.finished_at,
        created_at=run.created_at,
    )


def _to_stream_state_dto(state: ConnectionStreamState) -> StreamStateSummaryDTO:
    return StreamStateSummaryDTO(
        state_id=state.id,
        tenant_id=state.tenant_id,
        connection_id=state.connection_id,
        stream_name=state.stream_name,
        cursor_field=state.cursor_field,
        cursor_value=state.cursor_value,
        records_synced_count=state.records_synced_count,
        last_synced_at=state.last_synced_at,
    )


class TriggerSyncRunUseCase:
    """Queues a PENDING SyncRun and emits SyncRunRequestedEvent into the Control Plane outbox."""

    def __init__(self, *, control_plane_uow: IpControlPlaneUnitOfWorkPort) -> None:
        self._cp_uow = control_plane_uow

    async def execute(self, command: TriggerSyncRunCommand) -> Result[SyncRunSummaryDTO, IpError]:
        bound = logger.bind(
            tenant_id=command.tenant_id,
            connection_id=command.connection_id,
            stream=command.stream_name,
        )
        bound.info("trigger_sync_run.received")
        async with self._cp_uow:
            conn = await self._cp_uow.connections.get_by_id(command.connection_id)
            if conn is None or conn.tenant_id != command.tenant_id:
                bound.error("trigger_sync_run.connection_not_found")
                return Result.err(ConnectionNotFoundError.for_id(command.connection_id))

            if conn.status == ConnectionStatus.DEACTIVATED:
                bound.error("trigger_sync_run.connection_deactivated")
                return Result.err(ConnectionDeactivatedError.for_id(command.connection_id))

            active_run = await self._cp_uow.sync_runs.get_active_run(
                connection_id=command.connection_id,
                stream=command.stream_name,
                tenant_id=command.tenant_id,
            )
            if active_run is not None:
                bound.error(
                    "trigger_sync_run.active_run_exists",
                    existing_run_id=active_run.id,
                    existing_status=active_run.status.value,
                )
                return Result.err(
                    ActiveSyncRunAlreadyExistsError.for_stream(
                        command.connection_id, command.stream_name
                    )
                )

            state = await self._cp_uow.stream_states.get_by_stream(
                tenant_id=command.tenant_id,
                connection_id=command.connection_id,
                stream_name=command.stream_name,
            )
            latest_gen = await self._cp_uow.sync_runs.get_latest_generation_id(
                tenant_id=command.tenant_id,
                connection_id=command.connection_id,
                stream=command.stream_name,
            )

            if command.forced_kind is not None:
                kind = command.forced_kind
            elif state is None or not state.cursor_value:
                kind = SyncRunKind.INITIAL
            else:
                kind = SyncRunKind.INCREMENTAL

            generation_id = (
                latest_gen + 1 if kind == SyncRunKind.FULL_REFRESH else max(1, latest_gen)
            )
            start_cursor = (
                None
                if kind == SyncRunKind.FULL_REFRESH
                else (state.cursor_value if state is not None else None)
            )

            sync_run = SyncRun.request(
                tenant_id=command.tenant_id,
                connection_id=command.connection_id,
                stream=command.stream_name,
                kind=kind,
                generation_id=generation_id,
                start_checkpoint=start_cursor,
                correlation_id=command.correlation_id,
            )
            await self._cp_uow.sync_runs.save(sync_run)
            await self._cp_uow.commit()

            bound.info(
                "trigger_sync_run.completed",
                run_id=sync_run.id,
                kind=kind.value,
                generation_id=generation_id,
                trace_id=sync_run.trace_id,
            )
            return Result.ok(_to_sync_run_dto(sync_run))


class ListSyncRunsUseCase:
    """Lists recent SyncRuns for a connection."""

    def __init__(self, *, control_plane_uow: IpControlPlaneUnitOfWorkPort) -> None:
        self._cp_uow = control_plane_uow

    async def execute(
        self, query: ListSyncRunsQuery
    ) -> Result[tuple[SyncRunSummaryDTO, ...], IpError]:
        bound = logger.bind(
            tenant_id=query.tenant_id,
            connection_id=query.connection_id,
        )
        bound.info("list_sync_runs.received")
        async with self._cp_uow:
            conn = await self._cp_uow.connections.get_by_id(query.connection_id)
            if conn is None or conn.tenant_id != query.tenant_id:
                bound.error("list_sync_runs.connection_not_found")
                return Result.err(ConnectionNotFoundError.for_id(query.connection_id))

            runs = await self._cp_uow.sync_runs.list_by_connection(
                tenant_id=query.tenant_id,
                connection_id=query.connection_id,
                limit=query.limit,
            )
            dtos = tuple(_to_sync_run_dto(r) for r in runs)
            bound.info("list_sync_runs.completed", count=len(dtos))
            return Result.ok(dtos)


class GetSyncRunUseCase:
    """Retrieves a specific SyncRun by ID for a connection."""

    def __init__(self, *, control_plane_uow: IpControlPlaneUnitOfWorkPort) -> None:
        self._cp_uow = control_plane_uow

    async def execute(self, query: GetSyncRunQuery) -> Result[SyncRunSummaryDTO, IpError]:
        bound = logger.bind(
            tenant_id=query.tenant_id,
            connection_id=query.connection_id,
            run_id=query.run_id,
        )
        bound.info("get_sync_run.received")
        async with self._cp_uow:
            conn = await self._cp_uow.connections.get_by_id(query.connection_id)
            if conn is None or conn.tenant_id != query.tenant_id:
                bound.error("get_sync_run.connection_not_found")
                return Result.err(ConnectionNotFoundError.for_id(query.connection_id))

            run = await self._cp_uow.sync_runs.get_by_id(
                run_id=query.run_id,
                tenant_id=query.tenant_id,
            )
            if run is None or run.connection_id != query.connection_id:
                bound.error("get_sync_run.not_found")
                return Result.err(SyncRunNotFoundError.for_id(query.run_id))

            bound.info("get_sync_run.completed", status=run.status.value)
            return Result.ok(_to_sync_run_dto(run))


class ListStreamStatesUseCase:
    """Lists all stream state checkpoints recorded for a connection."""

    def __init__(self, *, control_plane_uow: IpControlPlaneUnitOfWorkPort) -> None:
        self._cp_uow = control_plane_uow

    async def execute(
        self, query: ListStreamStatesQuery
    ) -> Result[tuple[StreamStateSummaryDTO, ...], IpError]:
        bound = logger.bind(
            tenant_id=query.tenant_id,
            connection_id=query.connection_id,
        )
        bound.info("list_stream_states.received")
        async with self._cp_uow:
            conn = await self._cp_uow.connections.get_by_id(query.connection_id)
            if conn is None or conn.tenant_id != query.tenant_id:
                bound.error("list_stream_states.connection_not_found")
                return Result.err(ConnectionNotFoundError.for_id(query.connection_id))

            states = await self._cp_uow.stream_states.list_by_connection(
                tenant_id=query.tenant_id,
                connection_id=query.connection_id,
            )
            dtos = tuple(_to_stream_state_dto(s) for s in states)
            bound.info("list_stream_states.completed", count=len(dtos))
            return Result.ok(dtos)


class ResetStreamCheckpointUseCase:
    """Resets a stream's incremental checkpoint cursor to force full historical re-sync."""

    def __init__(self, *, control_plane_uow: IpControlPlaneUnitOfWorkPort) -> None:
        self._cp_uow = control_plane_uow

    async def execute(
        self, command: ResetStreamCheckpointCommand
    ) -> Result[StreamStateSummaryDTO, IpError]:
        bound = logger.bind(
            tenant_id=command.tenant_id,
            connection_id=command.connection_id,
            stream=command.stream_name,
        )
        bound.info("reset_stream_checkpoint.received")
        async with self._cp_uow:
            conn = await self._cp_uow.connections.get_by_id(command.connection_id)
            if conn is None or conn.tenant_id != command.tenant_id:
                bound.error("reset_stream_checkpoint.connection_not_found")
                return Result.err(ConnectionNotFoundError.for_id(command.connection_id))

            active_run = await self._cp_uow.sync_runs.get_active_run(
                connection_id=command.connection_id,
                stream=command.stream_name,
                tenant_id=command.tenant_id,
            )
            if active_run is not None:
                bound.error(
                    "reset_stream_checkpoint.active_run_exists",
                    existing_run_id=active_run.id,
                )
                return Result.err(
                    ActiveSyncRunAlreadyExistsError.for_stream(
                        command.connection_id, command.stream_name
                    )
                )

            state = await self._cp_uow.stream_states.get_by_stream(
                tenant_id=command.tenant_id,
                connection_id=command.connection_id,
                stream_name=command.stream_name,
            )
            if state is None:
                state = ConnectionStreamState.create(
                    tenant_id=command.tenant_id,
                    connection_id=command.connection_id,
                    stream_name=command.stream_name,
                )
            else:
                state.reset_checkpoint()

            await self._cp_uow.stream_states.save(state)
            await self._cp_uow.commit()

            bound.info("reset_stream_checkpoint.completed", state_id=state.id)
            return Result.ok(_to_stream_state_dto(state))


__all__ = [
    "GetSyncRunQuery",
    "GetSyncRunUseCase",
    "ListStreamStatesQuery",
    "ListStreamStatesUseCase",
    "ListSyncRunsQuery",
    "ListSyncRunsUseCase",
    "ResetStreamCheckpointCommand",
    "ResetStreamCheckpointUseCase",
    "StreamStateSummaryDTO",
    "SyncRunSummaryDTO",
    "TriggerSyncRunCommand",
    "TriggerSyncRunUseCase",
]
