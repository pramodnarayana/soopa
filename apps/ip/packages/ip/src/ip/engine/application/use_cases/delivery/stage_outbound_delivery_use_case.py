"""Layer 4 to Layer 5 Pure Egress Outbox Staging Use Case.

Stages an `OutboundRecord(PENDING)` and its `OutboundRecordCreatedEvent` into `public.ip_outbox`
without performing any external HTTP calls or OAuth2 token exchanges inside `ip-orchestrator-worker`.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field

import structlog
from seedwork.domain.types import JsonDict
from seedwork.utils import generate_id

from ip.engine.domain.constants import DEFAULT_IDEMPOTENCY_HEADER, IpIdPrefix
from ip.engine.domain.dispatch.classifier import redact_sensitive_headers
from ip.engine.domain.dispatch.enums import (
    HttpWriteOperation,
    OutboundConflictStrategy,
    OutboundDispatchStatus,
)
from ip.engine.domain.dispatch.outbound_record import OutboundRecord
from ip.engine.domain.exceptions import (
    ConnectionNotFoundError,
    IpError,
    Result,
    TenantShardNotFoundError,
)
from ip.engine.ports.outbound.tiered_storage_port import TieredStoragePort
from ip.engine.ports.outbound.uow import (
    IpControlPlaneUnitOfWorkPort,
    IpDataPlaneUnitOfWorkPort,
    IpDataPlaneUnitOfWorkProviderPort,
)

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class StageOutboundDeliveryCommand:
    """Command staging a Layer-5 outbound dispatch onto the Egress Queue."""

    tenant_id: str
    connection_id: str
    stream_name: str
    operation: str = HttpWriteOperation.CREATE.value
    payload: JsonDict = field(default_factory=dict)
    record_id: str | None = None
    idempotency_key: str | None = None
    idempotency_header_name: str = DEFAULT_IDEMPOTENCY_HEADER
    headers: Mapping[str, str] = field(default_factory=dict)
    conflict_strategy: OutboundConflictStrategy = OutboundConflictStrategy.FAIL
    trace_id: str | None = None
    correlation_id: str | None = None
    parent_trace_id: str | None = None
    original_trace_id: str | None = None
    replay_count: int = 0
    causation_depth: int = 0


@dataclass(frozen=True)
class StageOutboundDeliveryResponse:
    """Structured result of staging an `OutboundRecord(PENDING)` into `public.ip_outbox`."""

    outbound_record_id: str
    status: OutboundDispatchStatus
    trace_id: str
    idempotency_key: str
    record_id: str
    was_deduplicated: bool = False


def compute_staging_idempotency_key(command: StageOutboundDeliveryCommand) -> str:
    """Computes a deterministic SHA-256 idempotency key when none is explicitly provided."""
    if command.idempotency_key and command.idempotency_key.strip():
        return command.idempotency_key.strip()
    canonical_payload = json.dumps(command.payload, separators=(",", ":"), sort_keys=True)
    raw = (
        f"{command.tenant_id}:{command.connection_id}:{command.stream_name}:"
        f"{command.operation}:{command.record_id or ''}:{canonical_payload}"
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class StageOutboundDeliveryUseCase:
    """Pure Layer-4 Egress Stager guaranteeing bulkhead isolation from external HTTP I/O."""

    def __init__(
        self,
        *,
        control_plane_uow: IpControlPlaneUnitOfWorkPort,
        tiered_storage: TieredStoragePort,
        data_plane_uow: IpDataPlaneUnitOfWorkPort | None = None,
        data_plane_uow_provider: IpDataPlaneUnitOfWorkProviderPort | None = None,
    ) -> None:
        if data_plane_uow is None and data_plane_uow_provider is None:
            raise ValueError("Either data_plane_uow or data_plane_uow_provider must be provided.")
        self._control_plane_uow = control_plane_uow
        self._tiered_storage = tiered_storage
        self._data_plane_uow = data_plane_uow
        self._data_plane_uow_provider = data_plane_uow_provider

    @contextlib.asynccontextmanager
    async def _open_uow(
        self,
        tenant_id: str,
        shard_info: tuple[str, str] | None = None,
    ) -> AsyncIterator[IpDataPlaneUnitOfWorkPort]:
        if self._data_plane_uow is not None:
            async with self._data_plane_uow as uow:
                yield uow
            return
        assert self._data_plane_uow_provider is not None
        assert shard_info is not None
        shard_id, shard_dsn = shard_info
        async with self._data_plane_uow_provider.get_data_plane_uow(
            tenant_id, shard_id, shard_dsn
        ) as uow:
            yield uow

    async def _resolve_tenant_shard_info(
        self, tenant_id: str
    ) -> Result[tuple[str, str] | None, IpError]:
        if self._data_plane_uow is not None or self._data_plane_uow_provider is None:
            return Result.ok(None)
        shard_info_res = await self._data_plane_uow_provider.resolve_shard_info(tenant_id)
        if shard_info_res.is_err:
            return Result.err(
                TenantShardNotFoundError(
                    tenant_id=tenant_id,
                    message=(
                        f"Tenant shard resolution failed for tenant {tenant_id}: "
                        f"{shard_info_res.unwrap_err().message}"
                    ),
                    details={"tenant_id": tenant_id},
                )
            )
        return Result.ok(shard_info_res.unwrap())

    async def execute(
        self, command: StageOutboundDeliveryCommand
    ) -> Result[StageOutboundDeliveryResponse, IpError]:
        """Stages `OutboundRecord(PENDING)` + `OutboundRecordCreatedEvent` in a single DB commit."""
        trace_id = command.trace_id or generate_id(IpIdPrefix.TRACE.value)
        idempotency_key = compute_staging_idempotency_key(command)

        shard_res = await self._resolve_tenant_shard_info(command.tenant_id)
        if shard_res.is_err:
            return Result.err(shard_res.unwrap_err())
        shard_info = shard_res.value

        async with self._control_plane_uow:
            connection = await self._control_plane_uow.connections.get_by_id(command.connection_id)
        if connection is None or connection.tenant_id != command.tenant_id:
            logger.error(
                "outbound_staging_connection_not_found",
                tenant_id=command.tenant_id,
                connection_id=command.connection_id,
                trace_id=trace_id,
            )
            return Result.err(ConnectionNotFoundError.for_id(command.connection_id))

        async with self._open_uow(command.tenant_id, shard_info=shard_info) as uow:
            existing = await uow.outbound_records.get_by_idempotency_key(
                tenant_id=command.tenant_id,
                connection_id=command.connection_id,
                idempotency_key=idempotency_key,
            )
            if existing is not None:
                logger.info(
                    "outbound_staging_deduplicated",
                    tenant_id=command.tenant_id,
                    connection_id=command.connection_id,
                    outbound_record_id=existing.id,
                    idempotency_key=idempotency_key,
                    status=existing.status.value,
                    trace_id=existing.trace_id,
                )
                return Result.ok(
                    StageOutboundDeliveryResponse(
                        outbound_record_id=existing.id,
                        status=existing.status,
                        trace_id=existing.trace_id,
                        idempotency_key=idempotency_key,
                        record_id=existing.external_record_id or command.record_id or "",
                        was_deduplicated=True,
                    )
                )

            payload_bytes = json.dumps(
                command.payload,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
            req_storage = await self._tiered_storage.store(
                tenant_id=command.tenant_id,
                trace_id=trace_id,
                payload_bytes=payload_bytes,
                parsed_payload=command.payload,
            )
            base_url = str(
                connection.public_config.get("base_url")
                or connection.public_config.get("endpoint_url")
                or connection.public_config.get("host")
                or f"https://{connection.app_id}.local"
            ).rstrip("/")
            initial_target_url = f"{base_url}/{command.stream_name.lstrip('/')}"
            raw_dispatch_headers = {
                **command.headers,
                command.idempotency_header_name: idempotency_key,
            }
            initial_headers: JsonDict = redact_sensitive_headers(raw_dispatch_headers)

            outbound_record = OutboundRecord.create_pending(
                tenant_id=command.tenant_id,
                connection_id=command.connection_id,
                app_id=connection.app_id,
                stream_name=command.stream_name,
                operation=command.operation,
                idempotency_key=idempotency_key,
                external_record_id=command.record_id,
                target_url=initial_target_url,
                http_method="POST",
                payload_bytes=payload_bytes,
                is_inlined=req_storage.is_inlined,
                trace_id=trace_id,
                correlation_id=command.correlation_id,
                parent_trace_id=command.parent_trace_id,
                original_trace_id=command.original_trace_id,
                replay_count=command.replay_count,
                request_headers=initial_headers,
                request_body=req_storage.raw_payload,
                request_s3_key=req_storage.s3_key,
                attempt_number=1,
                conflict_strategy=command.conflict_strategy.value,
                dispatch_headers=raw_dispatch_headers,
                causation_depth=command.causation_depth,
            )
            await uow.outbound_records.save(outbound_record)
            await uow.commit()

        logger.info(
            "outbound_delivery_staged",
            tenant_id=command.tenant_id,
            connection_id=command.connection_id,
            outbound_record_id=outbound_record.id,
            idempotency_key=idempotency_key,
            trace_id=trace_id,
            causation_depth=command.causation_depth,
        )
        return Result.ok(
            StageOutboundDeliveryResponse(
                outbound_record_id=outbound_record.id,
                status=OutboundDispatchStatus.PENDING,
                trace_id=trace_id,
                idempotency_key=idempotency_key,
                record_id=command.record_id or "",
                was_deduplicated=False,
            )
        )


__all__ = [
    "StageOutboundDeliveryCommand",
    "StageOutboundDeliveryResponse",
    "StageOutboundDeliveryUseCase",
    "compute_staging_idempotency_key",
]
