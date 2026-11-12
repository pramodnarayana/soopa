"""Use case orchestrating Control Plane connection authorization and L1 Data Plane push ingestion."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import structlog
from seedwork.domain.types import JsonValue

from ip.engine.application.use_cases.ingestion.receive_push_use_case import (
    ReceivePushCommand,
    ReceivePushExecutorFactory,
    ReceivePushResultDTO,
)
from ip.engine.domain.connection.enums import ConnectionStatus
from ip.engine.domain.exceptions import (
    ConnectionDeactivatedError,
    ConnectionNotFoundError,
    IpError,
    Result,
)
from ip.engine.ports.outbound.uow import (
    IpControlPlaneUnitOfWorkPort,
    IpDataPlaneUnitOfWorkProviderPort,
)

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class IngestConnectionWebhookCommand:
    """Command to validate connection ownership/status and ingest an external push webhook."""

    tenant_id: str
    app_id: str
    connection_id: str
    stream_name: str
    raw_payload: bytes
    headers: Mapping[str, JsonValue]
    external_event_id: str | None = None
    correlation_id: str | None = None


class IngestConnectionWebhookUseCase:
    """Validates Control Plane connection state before delegating L1 storage to `ReceivePushExecutorPort`."""

    def __init__(
        self,
        *,
        control_plane_uow: IpControlPlaneUnitOfWorkPort,
        data_plane_uow_provider: IpDataPlaneUnitOfWorkProviderPort,
        push_executor_factory: ReceivePushExecutorFactory,
    ) -> None:
        self._cp_uow = control_plane_uow
        self._dp_uow_provider = data_plane_uow_provider
        self._push_executor_factory = push_executor_factory

    async def execute(
        self, command: IngestConnectionWebhookCommand
    ) -> Result[ReceivePushResultDTO, IpError]:
        bound = logger.bind(
            tenant_id=command.tenant_id,
            app_id=command.app_id,
            connection_id=command.connection_id,
            stream_name=command.stream_name,
            correlation_id=command.correlation_id,
        )
        bound.info("ingest_connection_webhook.received")

        async with self._cp_uow:
            conn = await self._cp_uow.connections.get_by_id(command.connection_id)
            if conn is None or conn.tenant_id != command.tenant_id:
                not_found_err = ConnectionNotFoundError.for_id(command.connection_id)
                bound.error(
                    "ingest_connection_webhook.connection_not_found",
                    error_code=not_found_err.code.value,
                )
                return Result.fail(not_found_err)

            if conn.app_id != command.app_id:
                mismatch_err = ConnectionNotFoundError.for_id(command.connection_id)
                bound.error(
                    "ingest_connection_webhook.app_mismatch",
                    expected_app_id=conn.app_id,
                    error_code=mismatch_err.code.value,
                )
                return Result.fail(mismatch_err)

            if conn.status == ConnectionStatus.DEACTIVATED:
                deact_err = ConnectionDeactivatedError.for_id(command.connection_id)
                bound.error(
                    "ingest_connection_webhook.connection_deactivated",
                    error_code=deact_err.code.value,
                )
                return Result.fail(deact_err)
            resolved_app_id = conn.app_id

        shard_res = await self._dp_uow_provider.resolve_shard_info(command.tenant_id)
        if shard_res.is_err:
            shard_err = shard_res.unwrap_err()
            bound.error(
                "ingest_connection_webhook.shard_resolution_failed",
                error_code=shard_err.code.value,
            )
            return Result.fail(shard_err)

        shard_id, shard_dsn = shard_res.unwrap()
        async with self._dp_uow_provider.get_data_plane_uow(
            tenant_id=command.tenant_id,
            shard_id=shard_id,
            shard_dsn=shard_dsn,
        ) as dp_uow:
            push_executor = self._push_executor_factory(dp_uow)
            push_result = await push_executor.execute(
                ReceivePushCommand(
                    tenant_id=command.tenant_id,
                    connection_id=command.connection_id,
                    app_id=resolved_app_id,
                    stream_name=command.stream_name,
                    raw_payload=command.raw_payload,
                    headers=command.headers,
                    external_event_id=command.external_event_id,
                    correlation_id=command.correlation_id,
                )
            )
        return Result.ok(push_result)


__all__ = ["IngestConnectionWebhookCommand", "IngestConnectionWebhookUseCase"]
