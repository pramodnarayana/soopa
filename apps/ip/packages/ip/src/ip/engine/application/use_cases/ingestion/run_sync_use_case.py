"""Use case for executing resilient, checkpointed pull sync runs across L1 Data Plane and Control Plane."""

from __future__ import annotations

import contextlib
import json
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import structlog
from security.ports.cipher_port import CipherPort
from seedwork.domain.types import JsonDict, JsonValue
from seedwork.id_registry import DomainIdPrefix
from seedwork.utils import generate_id

from ip.engine.application.use_cases.connections.token_manager_service import (
    GetValidCredentialsCommand,
    TokenManagerService,
)
from ip.engine.domain.enums import (
    IngestionMode,
    SyncRunKind,
    SyncRunStatus,
)
from ip.engine.domain.models.connection import Connection
from ip.engine.domain.models.inbound_record import InboundRecord
from ip.engine.domain.models.stream_state import ConnectionStreamState
from ip.engine.domain.models.sync_run import SyncRun
from ip.engine.ports.outbound.connector_port import SourceConnectorPort
from ip.engine.ports.outbound.tiered_storage_port import TieredStoragePort
from ip.engine.ports.outbound.uow import (
    IpControlPlaneUnitOfWorkPort,
    IpDataPlaneUnitOfWorkPort,
    IpDataPlaneUnitOfWorkProviderPort,
)
from ip.engine.ports.types import RecordEnvelopeDTO

logger = structlog.get_logger(__name__)


def calculate_lookback_cursor(
    cursor_value: str | None,
    lookback_seconds: int = 300,
) -> str | None:
    """Adjusts an ISO timestamp cursor backward by lookback_seconds to tolerate clock skew."""
    if not cursor_value:
        return None
    try:
        dt = datetime.fromisoformat(cursor_value.replace("Z", "+00:00"))
        adjusted = dt - timedelta(seconds=lookback_seconds)
        if dt.tzinfo is None:
            return adjusted.isoformat()
        return adjusted.astimezone(UTC).isoformat()
    except (ValueError, TypeError):
        return cursor_value


@dataclass(frozen=True)
class RunSyncCommand:
    """Command payload to execute a pull sync run for a connection stream."""

    tenant_id: str
    connection_id: str
    stream_name: str
    forced_kind: SyncRunKind | None = None
    lookback_seconds: int = 300
    max_pages: int = 500
    page_batch_size: int = 100
    trace_id: str | None = None
    correlation_id: str | None = None


@dataclass(frozen=True)
class RunSyncResultDTO:
    """Execution summary of a completed or failed pull sync run."""

    run_id: str
    tenant_id: str
    connection_id: str
    stream_name: str
    kind: str
    status: str
    pages_synced: int
    records_synced: int
    bytes_synced: int
    start_checkpoint: str | None = None
    end_checkpoint: str | None = None
    error_code: str | None = None
    error_message: str | None = None


class RunSyncUseCase:
    """Worker coordinator running pull streams, staging pages to L1 Data Plane, and persisting checkpoints in Control Plane."""

    def __init__(
        self,
        control_plane_uow: IpControlPlaneUnitOfWorkPort,
        tiered_storage: TieredStoragePort,
        cipher: CipherPort,
        connectors: Mapping[str, SourceConnectorPort],
        *,
        data_plane_uow: IpDataPlaneUnitOfWorkPort | None = None,
        data_plane_uow_provider: IpDataPlaneUnitOfWorkProviderPort | None = None,
        token_manager: TokenManagerService | None = None,
    ) -> None:
        self._control_plane_uow = control_plane_uow
        self._data_plane_uow = data_plane_uow
        self._data_plane_uow_provider = data_plane_uow_provider
        self._tiered_storage = tiered_storage
        self._cipher = cipher
        self._connectors = connectors
        self._token_manager = token_manager or TokenManagerService(
            control_plane_uow=control_plane_uow,
            cipher=cipher,
        )

    @contextlib.asynccontextmanager
    async def _open_uow(self, tenant_id: str) -> AsyncIterator[IpDataPlaneUnitOfWorkPort]:
        if self._data_plane_uow is not None:
            async with self._data_plane_uow as uow:
                yield uow
        elif self._data_plane_uow_provider is not None:
            shard_info_res = await self._data_plane_uow_provider.resolve_shard_info(tenant_id)
            if shard_info_res.is_err:
                raise RuntimeError(shard_info_res.unwrap_err().message)
            shard_id, shard_dsn = shard_info_res.unwrap()
            async with self._data_plane_uow_provider.get_data_plane_uow(
                tenant_id, shard_id, shard_dsn
            ) as uow:
                yield uow
        else:
            raise RuntimeError("Neither data_plane_uow nor data_plane_uow_provider was configured.")

    async def execute(self, command: RunSyncCommand) -> RunSyncResultDTO:
        trace_id = command.trace_id or generate_id(DomainIdPrefix.IP_TRACE.value)
        init_res = await self._init_sync_run(command, trace_id)
        if isinstance(init_res, RunSyncResultDTO):
            return init_res
        sync_run, start_cursor, kind, generation_id = init_res

        try:
            conn_ctx = await self._resolve_connection_context(command)
            if conn_ctx is None:
                return await self._fail_run(
                    sync_run,
                    "CONNECTION_NOT_FOUND",
                    "Connection or connector could not be resolved",
                )
            connection, connector, credentials = conn_ctx

            read_cursor = (
                calculate_lookback_cursor(start_cursor, command.lookback_seconds)
                if kind == SyncRunKind.INCREMENTAL
                else start_cursor
            )
            ingestion_mode = self._resolve_ingestion_mode(kind)

            capped = await self._execute_stream_pull(
                command=command,
                sync_run=sync_run,
                connection=connection,
                connector=connector,
                credentials=credentials,
                read_cursor=read_cursor,
                ingestion_mode=ingestion_mode,
                generation_id=generation_id,
                trace_id=trace_id,
            )
        except Exception as exc:
            logger.exception(
                "sync_run_execution_exception",
                run_id=sync_run.id,
                stream=command.stream_name,
                error=str(exc),
            )
            return await self._fail_run(sync_run, "STREAM_READ_ERROR", str(exc))

        if connector.last_error is not None:
            err = connector.last_error
            logger.error(
                "sync_run_connector_stream_error",
                run_id=sync_run.id,
                stream=command.stream_name,
                error_code=err.code.value,
                error=err.message,
                trace_id=trace_id,
            )
            return await self._fail_run(sync_run, err.code.value, err.message)

        if capped and sync_run.kind == SyncRunKind.FULL_REFRESH:
            logger.error(
                "sync_run_full_refresh_capped_incomplete",
                run_id=sync_run.id,
                stream=command.stream_name,
                max_pages=command.max_pages,
                trace_id=trace_id,
            )
            return await self._fail_run(
                sync_run,
                "MAX_PAGES_REACHED",
                f"FULL_REFRESH reached maximum page limit of {command.max_pages} pages before stream completion.",
            )

        return await self._complete_run(sync_run, start_cursor, trace_id)

    async def _init_sync_run(
        self, command: RunSyncCommand, trace_id: str
    ) -> tuple[SyncRun, str | None, SyncRunKind, int] | RunSyncResultDTO:
        async with self._control_plane_uow:
            active_run = await self._control_plane_uow.sync_runs.get_active_run(
                tenant_id=command.tenant_id,
                connection_id=command.connection_id,
                stream=command.stream_name,
            )
            if active_run is not None:
                logger.error(
                    "active_sync_run_already_exists",
                    existing_run_id=active_run.id,
                    tenant_id=command.tenant_id,
                    connection_id=command.connection_id,
                    stream=command.stream_name,
                    status=active_run.status.value,
                    trace_id=trace_id,
                )
                return RunSyncResultDTO(
                    run_id=active_run.id,
                    tenant_id=command.tenant_id,
                    connection_id=command.connection_id,
                    stream_name=command.stream_name,
                    kind=active_run.kind.value,
                    status="CONFLICT",
                    pages_synced=0,
                    records_synced=0,
                    bytes_synced=0,
                    start_checkpoint=active_run.start_checkpoint,
                    end_checkpoint=active_run.end_checkpoint,
                    error_code="ACTIVE_SYNC_RUN_EXISTS",
                    error_message=(
                        f"Active sync run '{active_run.id}' is already in state '{active_run.status.value}' "
                        f"for connection '{command.connection_id}' stream '{command.stream_name}'."
                    ),
                )

            state = await self._control_plane_uow.stream_states.get_by_stream(
                tenant_id=command.tenant_id,
                connection_id=command.connection_id,
                stream_name=command.stream_name,
            )
            latest_gen = await self._control_plane_uow.sync_runs.get_latest_generation_id(
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
            start_cursor = state.cursor_value if state else None

            sync_run = SyncRun.create(
                tenant_id=command.tenant_id,
                connection_id=command.connection_id,
                stream=command.stream_name,
                kind=kind,
                generation_id=generation_id,
                start_checkpoint=start_cursor,
                trace_id=trace_id,
            )
            sync_run.start()
            await self._control_plane_uow.sync_runs.save(sync_run)
            await self._control_plane_uow.commit()

        return sync_run, start_cursor, kind, generation_id

    async def _resolve_connection_context(
        self, command: RunSyncCommand
    ) -> tuple[Connection, SourceConnectorPort, JsonDict] | None:
        creds_res = await self._token_manager.get_valid_credentials(
            GetValidCredentialsCommand(
                tenant_id=command.tenant_id,
                connection_id=command.connection_id,
            )
        )
        if creds_res.is_err or creds_res.value is None:
            return None
        resolved = creds_res.value
        connector = self._connectors.get(resolved.app_id)
        if not connector or resolved.connection is None:
            return None
        return resolved.connection, connector, resolved.credentials

    async def _execute_stream_pull(
        self,
        *,
        command: RunSyncCommand,
        sync_run: SyncRun,
        connection: Connection,
        connector: SourceConnectorPort,
        credentials: JsonDict,
        read_cursor: str | None,
        ingestion_mode: IngestionMode,
        generation_id: int,
        trace_id: str,
    ) -> bool:
        current_page: list[RecordEnvelopeDTO] = []
        page_index = 0
        latest_page_cursor: str | None = None
        capped = False

        async for record_envelope in connector.read_stream(
            stream_name=command.stream_name,
            public_config=connection.resolved_public_config,
            credentials=credentials,
            cursor=read_cursor,
            limit=command.page_batch_size,
        ):
            if page_index >= command.max_pages:
                logger.info(
                    "sync_run_page_cap_reached",
                    run_id=sync_run.id,
                    max_pages=command.max_pages,
                    stream=command.stream_name,
                )
                capped = True
                break

            current_page.append(record_envelope)
            if record_envelope.cursor_value:
                latest_page_cursor = record_envelope.cursor_value

            if len(current_page) >= command.page_batch_size:
                page_index += 1
                await self._persist_page(
                    page=current_page,
                    sync_run=sync_run,
                    tenant_id=command.tenant_id,
                    connection_id=command.connection_id,
                    app_id=connection.app_id,
                    stream_name=command.stream_name,
                    ingestion_mode=ingestion_mode,
                    generation_id=generation_id,
                    next_cursor=latest_page_cursor,
                    trace_id=trace_id,
                )
                current_page = []

        if current_page:
            await self._persist_page(
                page=current_page,
                sync_run=sync_run,
                tenant_id=command.tenant_id,
                connection_id=command.connection_id,
                app_id=connection.app_id,
                stream_name=command.stream_name,
                ingestion_mode=ingestion_mode,
                generation_id=generation_id,
                next_cursor=latest_page_cursor,
                trace_id=trace_id,
            )

        return capped

    async def _complete_run(
        self, sync_run: SyncRun, start_cursor: str | None, trace_id: str
    ) -> RunSyncResultDTO:
        end_checkpoint = sync_run.end_checkpoint or start_cursor
        sync_run.succeed(end_checkpoint=end_checkpoint)
        async with self._control_plane_uow:
            await self._control_plane_uow.sync_runs.save(sync_run)
            await self._control_plane_uow.commit()

        logger.info(
            "sync_run_completed",
            run_id=sync_run.id,
            stream=sync_run.stream,
            kind=sync_run.kind.value,
            pages=sync_run.pages_synced,
            records=sync_run.records_synced,
            bytes=sync_run.bytes_synced,
            trace_id=trace_id,
        )

        return RunSyncResultDTO(
            run_id=sync_run.id,
            tenant_id=sync_run.tenant_id,
            connection_id=sync_run.connection_id,
            stream_name=sync_run.stream,
            kind=sync_run.kind.value,
            status=sync_run.status.value,
            pages_synced=sync_run.pages_synced,
            records_synced=sync_run.records_synced,
            bytes_synced=sync_run.bytes_synced,
            start_checkpoint=sync_run.start_checkpoint,
            end_checkpoint=sync_run.end_checkpoint,
        )

    async def _persist_page(
        self,
        *,
        page: list[RecordEnvelopeDTO],
        sync_run: SyncRun,
        tenant_id: str,
        connection_id: str,
        app_id: str,
        stream_name: str,
        ingestion_mode: IngestionMode,
        generation_id: int,
        next_cursor: str | None,
        trace_id: str,
    ) -> None:
        """Stores page in Data Plane and atomically updates checkpoint and sync run counters in Control Plane."""
        page_payload: list[JsonValue] = [envelope.data for envelope in page]
        page_bytes = json.dumps(page_payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        parsed_dict: JsonDict | None = {"records": page_payload}

        # 1. Store raw payload in Data Plane (Tiered Storage)
        storage_result = await self._tiered_storage.store(
            tenant_id=tenant_id,
            trace_id=trace_id,
            payload_bytes=page_bytes,
            parsed_payload=parsed_dict,
        )

        # 2. Create InboundRecord aggregate root (emits InboundRecordCreatedEvent)
        inbound_record = InboundRecord.create(
            tenant_id=tenant_id,
            connection_id=connection_id,
            app_id=app_id,
            stream_name=stream_name,
            payload_bytes=page_bytes,
            is_inlined=storage_result.is_inlined,
            request_body=storage_result.raw_payload,
            request_s3_key=storage_result.s3_key,
            response_status_code=200,
            trace_id=trace_id,
            ingestion_mode=ingestion_mode,
            sync_run_id=sync_run.id,
            generation_id=generation_id,
        )

        # 3. Persist to Data Plane
        async with self._open_uow(tenant_id) as dp_uow:
            await dp_uow.inbound_records.save(inbound_record)
            await dp_uow.commit()

        # 4. Update cursor checkpoint and SyncRun counters in Control Plane
        async with self._control_plane_uow:
            state = await self._control_plane_uow.stream_states.get_by_stream(
                tenant_id=tenant_id,
                connection_id=connection_id,
                stream_name=stream_name,
            )
            if state is None:
                state = ConnectionStreamState.create(
                    tenant_id=tenant_id,
                    connection_id=connection_id,
                    stream_name=stream_name,
                    initial_cursor=next_cursor,
                )
            if next_cursor:
                state.advance_checkpoint(
                    new_cursor_value=next_cursor,
                    records_in_batch=len(page),
                )
            await self._control_plane_uow.stream_states.save(state)

            sync_run.record_page(
                records_in_page=len(page),
                bytes_size=len(page_bytes),
                next_checkpoint=next_cursor,
            )
            await self._control_plane_uow.sync_runs.save(sync_run)
            await self._control_plane_uow.commit()

    async def _fail_run(
        self, sync_run: SyncRun, error_code: str, error_message: str
    ) -> RunSyncResultDTO:
        sync_run.fail(error_code=error_code, error_message=error_message)
        async with self._control_plane_uow:
            await self._control_plane_uow.sync_runs.save(sync_run)
            await self._control_plane_uow.commit()

        return RunSyncResultDTO(
            run_id=sync_run.id,
            tenant_id=sync_run.tenant_id,
            connection_id=sync_run.connection_id,
            stream_name=sync_run.stream,
            kind=sync_run.kind.value,
            status=SyncRunStatus.FAILED.value,
            pages_synced=sync_run.pages_synced,
            records_synced=sync_run.records_synced,
            bytes_synced=sync_run.bytes_synced,
            start_checkpoint=sync_run.start_checkpoint,
            end_checkpoint=sync_run.end_checkpoint,
            error_code=error_code,
            error_message=error_message,
        )

    @staticmethod
    def _resolve_ingestion_mode(kind: SyncRunKind) -> IngestionMode:
        if kind == SyncRunKind.INITIAL:
            return IngestionMode.PULL_INITIAL
        if kind == SyncRunKind.INCREMENTAL:
            return IngestionMode.PULL_INCREMENTAL
        if kind == SyncRunKind.FULL_REFRESH:
            return IngestionMode.PULL_FULL_REFRESH
        return IngestionMode.PULL_RECONCILIATION
