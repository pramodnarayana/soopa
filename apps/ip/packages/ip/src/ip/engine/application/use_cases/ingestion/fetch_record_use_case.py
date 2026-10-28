"""Use case for asynchronous Fetch-on-Notify (Thin Push) fetching and L1 staging."""

from __future__ import annotations

import contextlib
import json
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass

import structlog
from security.ports.cipher_port import CipherPort
from seedwork.id_registry import DomainIdPrefix
from seedwork.utils import generate_id

from ip.engine.application.use_cases.connections.token_manager_service import (
    GetValidCredentialsCommand,
    TokenManagerService,
)
from ip.engine.domain.enums import IngestionMode
from ip.engine.domain.models.inbound_record import InboundRecord
from ip.engine.ports.outbound.connector_port import SourceConnectorPort
from ip.engine.ports.outbound.tiered_storage_port import TieredStoragePort
from ip.engine.ports.outbound.uow import (
    IpControlPlaneUnitOfWorkPort,
    IpDataPlaneUnitOfWorkPort,
    IpDataPlaneUnitOfWorkProviderPort,
)

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class FetchRecordCommand:
    """Command payload to execute a pull fetch for an individual thin-notified record."""

    tenant_id: str
    connection_id: str
    stream_name: str
    record_id: str
    parent_trace_id: str | None = None
    trace_id: str | None = None
    correlation_id: str | None = None


@dataclass(frozen=True)
class FetchRecordResultDTO:
    """Result of FetchRecordUseCase execution."""

    status: str
    trace_id: str
    record_id: str
    inbound_record_id: str | None = None
    is_inlined: bool = True


class FetchRecordUseCase:
    """Fetch-on-Notify worker coordinator fetching source records and staging them in L1 Data Plane."""

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
        if data_plane_uow is None and data_plane_uow_provider is None:
            raise ValueError("Either data_plane_uow or data_plane_uow_provider must be provided.")
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
    async def _open_uow(
        self,
        tenant_id: str,
        shard_info: tuple[str, str] | None = None,
    ) -> AsyncIterator[IpDataPlaneUnitOfWorkPort]:
        if self._data_plane_uow is not None:
            async with self._data_plane_uow as uow:
                yield uow
        elif self._data_plane_uow_provider is not None:
            if shard_info is None:
                shard_info_res = await self._data_plane_uow_provider.resolve_shard_info(tenant_id)
                if shard_info_res.is_err:
                    raise RuntimeError(shard_info_res.unwrap_err().message)
                shard_info = shard_info_res.unwrap()
            shard_id, shard_dsn = shard_info
            async with self._data_plane_uow_provider.get_data_plane_uow(
                tenant_id, shard_id, shard_dsn
            ) as uow:
                yield uow
        else:
            raise RuntimeError("Neither data_plane_uow nor data_plane_uow_provider was configured.")

    async def execute(self, command: FetchRecordCommand) -> FetchRecordResultDTO:
        trace_id = command.trace_id or generate_id(DomainIdPrefix.IP_TRACE.value)

        # 0. Pre-resolve tenant shard before pulling remote record or offloading payload
        shard_info: tuple[str, str] | None = None
        if self._data_plane_uow is None and self._data_plane_uow_provider is not None:
            shard_info_res = await self._data_plane_uow_provider.resolve_shard_info(
                command.tenant_id
            )
            if shard_info_res.is_err:
                logger.error(
                    "fetch_record_shard_resolution_failed",
                    tenant_id=command.tenant_id,
                    error=shard_info_res.unwrap_err().message,
                    trace_id=trace_id,
                )
                return FetchRecordResultDTO(
                    status="TENANT_SHARD_NOT_FOUND",
                    trace_id=trace_id,
                    record_id=command.record_id,
                )
            shard_info = shard_info_res.unwrap()

        # 1. Retrieve connection config & valid credentials via unified TokenManagerService
        creds_res = await self._token_manager.get_valid_credentials(
            GetValidCredentialsCommand(
                tenant_id=command.tenant_id,
                connection_id=command.connection_id,
            )
        )
        if creds_res.is_err or creds_res.value is None:
            err_code = creds_res.error.code.value if creds_res.error else "CONNECTION_NOT_FOUND"
            return FetchRecordResultDTO(
                status=err_code,
                trace_id=trace_id,
                record_id=command.record_id,
            )
        resolved = creds_res.value
        connector = self._connectors.get(resolved.app_id)
        if not connector:
            logger.error(
                "fetch_record_connector_not_found",
                app_id=resolved.app_id,
                connection_id=command.connection_id,
                trace_id=trace_id,
            )
            return FetchRecordResultDTO(
                status="CONNECTOR_NOT_FOUND",
                trace_id=trace_id,
                record_id=command.record_id,
            )
        resolved_app_id = resolved.app_id
        credentials = resolved.credentials
        public_config = resolved.public_config

        # 2. Fetch the discrete record from external app
        record_envelope = await connector.fetch_record(
            stream_name=command.stream_name,
            record_id=command.record_id,
            public_config=public_config,
            credentials=credentials,
        )

        if record_envelope is None:
            logger.error(
                "fetch_record_failed",
                connection_id=command.connection_id,
                stream_name=command.stream_name,
                record_id=command.record_id,
                trace_id=trace_id,
            )
            return FetchRecordResultDTO(
                status="NOT_FOUND",
                trace_id=trace_id,
                record_id=command.record_id,
            )

        # 3. Store the full payload in Data Plane (Tiered Storage)
        payload_bytes = json.dumps(
            record_envelope.data,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        parsed_dict = record_envelope.data if isinstance(record_envelope.data, dict) else None

        storage_result = await self._tiered_storage.store(
            tenant_id=command.tenant_id,
            trace_id=trace_id,
            payload_bytes=payload_bytes,
            parsed_payload=parsed_dict,
        )

        # 4. Create InboundRecord with FETCH_ON_NOTIFY mode and parent_trace_id link
        inbound = InboundRecord.create(
            tenant_id=command.tenant_id,
            connection_id=command.connection_id,
            app_id=resolved_app_id,
            stream_name=command.stream_name,
            payload_bytes=payload_bytes,
            is_inlined=storage_result.is_inlined,
            request_body=storage_result.raw_payload,
            request_s3_key=storage_result.s3_key,
            response_status_code=200,
            trace_id=trace_id,
            correlation_id=command.correlation_id,
            parent_trace_id=command.parent_trace_id,
            ingestion_mode=IngestionMode.FETCH_ON_NOTIFY,
        )

        # 5. Persist to Data Plane and commit
        async with self._open_uow(command.tenant_id, shard_info=shard_info) as uow:
            await uow.inbound_records.save(inbound)
            await uow.commit()

        logger.info(
            "fetch_record_completed",
            inbound_record_id=inbound.id,
            tenant_id=command.tenant_id,
            connection_id=command.connection_id,
            stream_name=command.stream_name,
            external_record_id=command.record_id,
            trace_id=trace_id,
        )

        return FetchRecordResultDTO(
            status="FETCHED",
            trace_id=trace_id,
            record_id=command.record_id,
            inbound_record_id=inbound.id,
            is_inlined=storage_result.is_inlined,
        )
