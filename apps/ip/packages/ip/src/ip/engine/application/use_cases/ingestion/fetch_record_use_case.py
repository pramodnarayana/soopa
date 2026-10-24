"""Use case for asynchronous Fetch-on-Notify (Thin Push) fetching and L1 staging."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass

import structlog
from security.ports.cipher_port import CipherPort
from seedwork.id_registry import DomainIdPrefix
from seedwork.utils import generate_id

from ip.engine.domain.enums import ConnectionStatus, IngestionMode
from ip.engine.domain.models.inbound_record import InboundRecord
from ip.engine.ports.outbound.connector_port import SourceConnectorPort
from ip.engine.ports.outbound.tiered_storage_port import TieredStoragePort
from ip.engine.ports.outbound.uow import (
    IpControlPlaneUnitOfWorkPort,
    IpDataPlaneUnitOfWorkPort,
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
        data_plane_uow: IpDataPlaneUnitOfWorkPort,
        tiered_storage: TieredStoragePort,
        cipher: CipherPort,
        connectors: Mapping[str, SourceConnectorPort],
    ) -> None:
        self._control_plane_uow = control_plane_uow
        self._data_plane_uow = data_plane_uow
        self._tiered_storage = tiered_storage
        self._cipher = cipher
        self._connectors = connectors

    async def execute(self, command: FetchRecordCommand) -> FetchRecordResultDTO:
        trace_id = command.trace_id or generate_id(DomainIdPrefix.IP_TRACE.value)

        # 1. Retrieve connection config from Control Plane
        async with self._control_plane_uow:
            connection = await self._control_plane_uow.connections.get_by_id(command.connection_id)
            if not connection or connection.tenant_id != command.tenant_id:
                logger.error(
                    "fetch_record_connection_not_found",
                    tenant_id=command.tenant_id,
                    connection_id=command.connection_id,
                    record_id=command.record_id,
                    trace_id=trace_id,
                )
                return FetchRecordResultDTO(
                    status="CONNECTION_NOT_FOUND",
                    trace_id=trace_id,
                    record_id=command.record_id,
                )

            if connection.status is ConnectionStatus.DEACTIVATED:
                logger.error(
                    "fetch_record_connection_deactivated",
                    tenant_id=command.tenant_id,
                    connection_id=command.connection_id,
                    record_id=command.record_id,
                    trace_id=trace_id,
                )
                return FetchRecordResultDTO(
                    status="CONNECTION_DEACTIVATED",
                    trace_id=trace_id,
                    record_id=command.record_id,
                )

            connector = self._connectors.get(connection.app_id)
            if not connector:
                logger.error(
                    "fetch_record_connector_not_found",
                    app_id=connection.app_id,
                    connection_id=command.connection_id,
                    trace_id=trace_id,
                )
                return FetchRecordResultDTO(
                    status="CONNECTOR_NOT_FOUND",
                    trace_id=trace_id,
                    record_id=command.record_id,
                )

            credentials = (
                self._cipher.decrypt(connection.encrypted_credentials)
                if connection.encrypted_credentials
                else {}
            )
            public_config = connection.resolved_public_config

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
            app_id=connection.app_id,
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
        async with self._data_plane_uow:
            await self._data_plane_uow.inbound_records.save(inbound)
            await self._data_plane_uow.commit()

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
