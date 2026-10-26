import contextlib
import hashlib
import json
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, field

import structlog
from seedwork.domain.types import JsonDict
from seedwork.id_registry import DomainIdPrefix
from seedwork.utils import generate_id

from ip.engine.application.use_cases.connections.token_manager_service import (
    GetValidCredentialsCommand,
    ResolvedConnectionCredentialsDTO,
    TokenManagerService,
)
from ip.engine.domain.constants import DEFAULT_IDEMPOTENCY_HEADER
from ip.engine.domain.enums import (
    AuthType,
    BatchFailurePolicy,
    FailureDisposition,
    HttpWriteOperation,
    OutboundConflictStrategy,
    OutboundDispatchStatus,
    OutboundFailureCategory,
    TokenRefreshPolicy,
)
from ip.engine.domain.exceptions import (
    ConnectionNotFoundError,
    ConnectorNotFoundError,
    IpError,
    Result,
    TenantShardNotFoundError,
)
from ip.engine.domain.models.outbound_record import OutboundRecord
from ip.engine.domain.services.outbound_error_classifier import classify_outbound_http_outcome
from ip.engine.ports.outbound.connector_port import DestinationConnectorPort
from ip.engine.ports.outbound.tiered_storage_port import TieredStoragePort
from ip.engine.ports.outbound.uow import (
    IpDataPlaneUnitOfWorkPort,
    IpDataPlaneUnitOfWorkProviderPort,
)
from ip.engine.ports.types import WriteRecordCommand, WriteResultDTO

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class DeliverOutboundRecordCommand:
    """Command payload to execute a single Layer-5 outbound mutation against a destination."""

    tenant_id: str
    connection_id: str
    stream_name: str
    operation: str = HttpWriteOperation.CREATE.value
    payload: JsonDict = field(default_factory=dict)
    record_id: str | None = None
    idempotency_key: str | None = None
    idempotency_header_name: str = DEFAULT_IDEMPOTENCY_HEADER
    headers: dict[str, str] = field(default_factory=dict)
    conflict_strategy: OutboundConflictStrategy = OutboundConflictStrategy.FAIL
    trace_id: str | None = None
    correlation_id: str | None = None
    parent_trace_id: str | None = None
    original_trace_id: str | None = None
    replay_count: int = 0
    attempt_number: int = 1


@dataclass(frozen=True)
class DeliverOutboundRecordResponse:
    """Structured result of a Layer-5 outbound dispatch."""

    outbound_record_id: str
    status: OutboundDispatchStatus
    trace_id: str
    idempotency_key: str
    record_id: str
    destination_id: str | None = None
    response_status_code: int | None = None
    response_body: JsonDict | None = None
    response_s3_key: str | None = None
    duration_ms: int | None = None
    was_deduplicated: bool = False
    was_token_refreshed: bool = False
    failure_category: OutboundFailureCategory | None = None
    retry_after_seconds: int | None = None
    error_code: str | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class DeliverOutboundBatchCommand:
    """Command to execute an item-isolated batch of Layer-5 outbound mutations."""

    tenant_id: str
    connection_id: str
    stream_name: str
    items: Sequence[DeliverOutboundRecordCommand]
    batch_idempotency_prefix: str | None = None
    failure_policy: BatchFailurePolicy = BatchFailurePolicy.CONTINUE_ALL


@dataclass(frozen=True)
class DeliverOutboundBatchResponse:
    """Aggregated outcome of an item-isolated Layer-5 batch delivery."""

    total_count: int
    delivered_count: int
    deduplicated_count: int
    retry_scheduled_count: int
    failed_count: int
    results: tuple[DeliverOutboundRecordResponse, ...]


def compute_deterministic_idempotency_key(command: DeliverOutboundRecordCommand) -> str:
    """Computes a deterministic SHA-256 idempotency key when the caller does not provide one."""
    if command.idempotency_key and command.idempotency_key.strip():
        return command.idempotency_key.strip()
    canonical_payload = json.dumps(command.payload, separators=(",", ":"), sort_keys=True)
    raw = (
        f"{command.tenant_id}:{command.connection_id}:{command.stream_name}:"
        f"{command.operation}:{command.record_id or ''}:{canonical_payload}"
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class DeliverOutboundRecordUseCase:
    """Layer-5 Outbound Delivery Coordinator.

    Guarantees:
    1. 2-Phase Idempotency Ledger: Short-circuits already-DELIVERED idempotency keys with zero
       network calls, and stages `OutboundRecord(PENDING)` prior to external HTTP dispatch.
    2. Coordinated OAuth2 Token Refresh + Reactive 401 Replay: Proactively refreshes expiring tokens
       under `TokenManagerService` lock and executes at most one reactive refresh + replay on HTTP 401.
    3. Dual S3 Tiered Offloading: Offloads both request and response bodies >= 64 KB to S3.
    4. First-Class Error Taxonomy: Classifies 429 (`Retry-After`), 5xx (`TRANSIENT`), 409 (`CONFLICT_IDEMPOTENT`),
       and 4xx (`VALIDATION_ERROR` / `TERMINAL`) without raising exceptions.
    """

    def __init__(
        self,
        *,
        tiered_storage: TieredStoragePort,
        token_manager: TokenManagerService,
        connectors: Mapping[str, DestinationConnectorPort],
        data_plane_uow: IpDataPlaneUnitOfWorkPort | None = None,
        data_plane_uow_provider: IpDataPlaneUnitOfWorkProviderPort | None = None,
    ) -> None:
        self._tiered_storage = tiered_storage
        self._token_manager = token_manager
        self._connectors = connectors
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

    async def _store_response_tier(
        self,
        *,
        tenant_id: str,
        trace_id: str,
        write_result: WriteResultDTO,
    ) -> tuple[JsonDict | None, str | None]:
        raw_bytes = write_result.raw_response_bytes
        if raw_bytes is None and write_result.response_body is not None:
            raw_bytes = json.dumps(
                write_result.response_body,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        if not raw_bytes:
            return write_result.response_body, None

        stored = await self._tiered_storage.store(
            tenant_id=tenant_id,
            trace_id=trace_id,
            payload_bytes=raw_bytes,
            parsed_payload=write_result.response_body,
        )
        if stored.is_inlined:
            return stored.raw_payload, None
        return None, stored.s3_key

    async def _resolve_tenant_shard_info(
        self, tenant_id: str
    ) -> Result[tuple[str, str] | None, IpError]:
        if self._data_plane_uow is not None or self._data_plane_uow_provider is None:
            return Result.ok(None)
        shard_info_res = await self._data_plane_uow_provider.resolve_shard_info(tenant_id)
        if shard_info_res.is_err:
            return Result.fail(
                TenantShardNotFoundError(
                    tenant_id=tenant_id,
                    message=f"Tenant shard resolution failed for tenant {tenant_id}: {shard_info_res.unwrap_err().message}",
                    details={"tenant_id": tenant_id},
                )
            )
        return Result.ok(shard_info_res.unwrap())

    async def execute(
        self,
        command: DeliverOutboundRecordCommand,
    ) -> Result[DeliverOutboundRecordResponse, IpError]:
        trace_id = command.trace_id or generate_id(DomainIdPrefix.IP_TRACE.value)
        idempotency_key = compute_deterministic_idempotency_key(command)

        shard_res = await self._resolve_tenant_shard_info(command.tenant_id)
        if shard_res.is_err:
            return Result.fail(shard_res.unwrap_err())
        shard_info = shard_res.value

        # ── Phase 1A: Idempotency Short-Circuit Check ────────────────────────
        async with self._open_uow(command.tenant_id, shard_info=shard_info) as uow:
            existing = await uow.outbound_records.get_by_idempotency_key(
                tenant_id=command.tenant_id,
                connection_id=command.connection_id,
                idempotency_key=idempotency_key,
            )
            if existing is not None and existing.status is OutboundDispatchStatus.DELIVERED:
                logger.info(
                    "outbound_delivery_deduplicated",
                    tenant_id=command.tenant_id,
                    connection_id=command.connection_id,
                    outbound_record_id=existing.id,
                    idempotency_key=idempotency_key,
                    trace_id=existing.trace_id,
                )
                return Result.ok(
                    DeliverOutboundRecordResponse(
                        outbound_record_id=existing.id,
                        status=OutboundDispatchStatus.DELIVERED,
                        trace_id=existing.trace_id,
                        idempotency_key=idempotency_key,
                        record_id=existing.external_record_id or command.record_id or "",
                        destination_id=existing.external_record_id,
                        response_status_code=existing.response_status_code,
                        response_body=existing.response_body,
                        response_s3_key=existing.response_s3_key,
                        duration_ms=existing.duration_ms,
                        was_deduplicated=True,
                    )
                )

        # ── Phase 1B: Resolve & Proactively Refresh Credentials ──────────────
        creds_res = await self._token_manager.get_valid_credentials(
            GetValidCredentialsCommand(
                tenant_id=command.tenant_id,
                connection_id=command.connection_id,
            )
        )
        if creds_res.is_err or creds_res.value is None:
            return Result.fail(
                creds_res.error or ConnectionNotFoundError.for_id(command.connection_id)
            )
        resolved_creds: ResolvedConnectionCredentialsDTO = creds_res.value
        was_token_refreshed = resolved_creds.was_refreshed

        connector = self._connectors.get(resolved_creds.app_id)
        if connector is None:
            logger.error(
                "outbound_delivery_connector_not_found",
                tenant_id=command.tenant_id,
                connection_id=command.connection_id,
                app_id=resolved_creds.app_id,
                trace_id=trace_id,
            )
            return Result.fail(ConnectorNotFoundError.for_app(resolved_creds.app_id))

        # ── Phase 1C: Stage PENDING OutboundRecord with Request Tiered Storage ─
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
            resolved_creds.public_config.get("base_url")
            or resolved_creds.public_config.get("endpoint_url")
            or resolved_creds.public_config.get("host")
            or f"https://{resolved_creds.app_id}.local"
        ).rstrip("/")
        initial_target_url = f"{base_url}/{command.stream_name.lstrip('/')}"
        initial_headers: JsonDict = {
            **command.headers,
            command.idempotency_header_name: idempotency_key,
        }

        async with self._open_uow(command.tenant_id, shard_info=shard_info) as uow:
            if existing is not None:
                outbound_record = existing
                outbound_record.mark_in_flight_attempt(attempt_number=command.attempt_number)
            else:
                outbound_record = OutboundRecord.create_pending(
                    tenant_id=command.tenant_id,
                    connection_id=command.connection_id,
                    app_id=resolved_creds.app_id,
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
                    attempt_number=command.attempt_number,
                )
            await uow.outbound_records.save(outbound_record)
            await uow.commit()

        # ── Phase 2A: Execute Outbound Write & Reactive 401 Single-Replay ────
        write_cmd = WriteRecordCommand(
            stream_name=command.stream_name,
            operation=command.operation,
            payload=command.payload,
            record_id=command.record_id,
            idempotency_key=idempotency_key,
            idempotency_header_name=command.idempotency_header_name,
            headers=dict(command.headers),
            correlation_id=command.correlation_id,
        )
        write_result = await connector.write_record(
            stream_name=command.stream_name,
            command=write_cmd,
            public_config=resolved_creds.public_config,
            credentials=resolved_creds.credentials,
        )

        if write_result.response_status_code == 401 and resolved_creds.auth_type in (
            AuthType.OAUTH2,
            AuthType.OAUTH2_CLIENT_CREDENTIALS,
        ):
            stale_token = str(resolved_creds.credentials.get("access_token") or "")
            reactive_refresh = await self._token_manager.get_valid_credentials(
                GetValidCredentialsCommand(
                    tenant_id=command.tenant_id,
                    connection_id=command.connection_id,
                    refresh_policy=TokenRefreshPolicy.FORCE_ROTATION,
                    stale_access_token=stale_token,
                )
            )
            if reactive_refresh.is_ok and reactive_refresh.value is not None:
                was_token_refreshed = True
                refreshed_dto = reactive_refresh.value
                write_result = await connector.write_record(
                    stream_name=command.stream_name,
                    command=write_cmd,
                    public_config=refreshed_dto.public_config,
                    credentials=refreshed_dto.credentials,
                )

        # ── Phase 2B: Offload Response (>= 64 KB) & Commit Final Audit State ─
        resp_inline_body, resp_s3_key = await self._store_response_tier(
            tenant_id=command.tenant_id,
            trace_id=trace_id,
            write_result=write_result,
        )
        classification = classify_outbound_http_outcome(
            write_result.response_status_code,
            headers=write_result.response_headers,
            conflict_strategy=command.conflict_strategy,
        )

        outbound_record.update_wire_target(
            target_url=write_result.target_url or initial_target_url,
            http_method=write_result.http_method or "POST",
            request_headers=write_result.request_headers or initial_headers,
        )

        external_id = write_result.destination_id or write_result.record_id or command.record_id

        if write_result.success or classification.is_success:
            status_code = write_result.response_status_code or 200
            outbound_record.mark_delivered(
                response_status_code=status_code,
                response_headers=write_result.response_headers,
                response_body=resp_inline_body,
                response_s3_key=resp_s3_key,
                duration_ms=write_result.duration_ms,
                external_record_id=external_id,
            )
            async with self._open_uow(command.tenant_id, shard_info=shard_info) as uow:
                await uow.outbound_records.save(outbound_record)
                await uow.commit()

            logger.info(
                "outbound_delivery_succeeded",
                tenant_id=command.tenant_id,
                connection_id=command.connection_id,
                outbound_record_id=outbound_record.id,
                idempotency_key=idempotency_key,
                status_code=status_code,
                duration_ms=write_result.duration_ms,
                trace_id=trace_id,
            )
            return Result.ok(
                DeliverOutboundRecordResponse(
                    outbound_record_id=outbound_record.id,
                    status=OutboundDispatchStatus.DELIVERED,
                    trace_id=trace_id,
                    idempotency_key=idempotency_key,
                    record_id=write_result.record_id or (command.record_id or ""),
                    destination_id=external_id,
                    response_status_code=status_code,
                    response_body=resp_inline_body,
                    response_s3_key=resp_s3_key,
                    duration_ms=write_result.duration_ms,
                    was_deduplicated=False,
                    was_token_refreshed=was_token_refreshed,
                    failure_category=classification.failure_category,
                )
            )

        error_msg = write_result.error_message or "Outbound delivery failed."
        retry_after = write_result.retry_after_seconds or classification.retry_after_seconds
        failure_cat = classification.failure_category or OutboundFailureCategory.TERMINAL

        if classification.disposition is FailureDisposition.RETRY:
            next_attempt = outbound_record.attempt_number + 1
            outbound_record.schedule_retry(
                error_message=error_msg,
                next_attempt=next_attempt,
                response_status_code=write_result.response_status_code,
                response_headers=write_result.response_headers,
                response_body=resp_inline_body,
                response_s3_key=resp_s3_key,
                duration_ms=write_result.duration_ms,
                failure_category=failure_cat.value,
                retry_after_seconds=retry_after,
            )
            async with self._open_uow(command.tenant_id, shard_info=shard_info) as uow:
                await uow.outbound_records.save(outbound_record)
                await uow.commit()

            logger.warning(
                "outbound_delivery_retry_scheduled",
                tenant_id=command.tenant_id,
                connection_id=command.connection_id,
                outbound_record_id=outbound_record.id,
                idempotency_key=idempotency_key,
                failure_category=failure_cat.value,
                retry_after_seconds=retry_after,
                next_attempt=next_attempt,
                trace_id=trace_id,
            )
            return Result.ok(
                DeliverOutboundRecordResponse(
                    outbound_record_id=outbound_record.id,
                    status=OutboundDispatchStatus.RETRY_SCHEDULED,
                    trace_id=trace_id,
                    idempotency_key=idempotency_key,
                    record_id=write_result.record_id or (command.record_id or ""),
                    destination_id=external_id,
                    response_status_code=write_result.response_status_code,
                    response_body=resp_inline_body,
                    response_s3_key=resp_s3_key,
                    duration_ms=write_result.duration_ms,
                    was_deduplicated=False,
                    was_token_refreshed=was_token_refreshed,
                    failure_category=failure_cat,
                    retry_after_seconds=retry_after,
                    error_code=write_result.error_code,
                    error_message=error_msg,
                )
            )

        outbound_record.mark_failed(
            error_message=error_msg,
            response_status_code=write_result.response_status_code,
            response_headers=write_result.response_headers,
            response_body=resp_inline_body,
            response_s3_key=resp_s3_key,
            duration_ms=write_result.duration_ms,
            failure_category=failure_cat.value,
        )
        async with self._open_uow(command.tenant_id, shard_info=shard_info) as uow:
            await uow.outbound_records.save(outbound_record)
            await uow.commit()

        logger.error(
            "outbound_delivery_terminal_failure",
            tenant_id=command.tenant_id,
            connection_id=command.connection_id,
            outbound_record_id=outbound_record.id,
            idempotency_key=idempotency_key,
            failure_category=failure_cat.value,
            status_code=write_result.response_status_code,
            error_message=error_msg,
            trace_id=trace_id,
        )
        return Result.ok(
            DeliverOutboundRecordResponse(
                outbound_record_id=outbound_record.id,
                status=OutboundDispatchStatus.FAILED,
                trace_id=trace_id,
                idempotency_key=idempotency_key,
                record_id=write_result.record_id or (command.record_id or ""),
                destination_id=external_id,
                response_status_code=write_result.response_status_code,
                response_body=resp_inline_body,
                response_s3_key=resp_s3_key,
                duration_ms=write_result.duration_ms,
                was_deduplicated=False,
                was_token_refreshed=was_token_refreshed,
                failure_category=failure_cat,
                error_code=write_result.error_code,
                error_message=error_msg,
            )
        )

    async def execute_batch(
        self,
        batch_command: DeliverOutboundBatchCommand,
    ) -> Result[DeliverOutboundBatchResponse, IpError]:
        """Executes a batch of outbound mutations with per-item idempotency isolation.

        Unlike n8n's `HttpRequestV3` (which re-executes all items from index 0 on retry),
        each item in the batch is assigned an isolated idempotency key and `OutboundRecord`.
        Retrying a partially-completed batch automatically skips already-DELIVERED items.
        """
        results: list[DeliverOutboundRecordResponse] = []
        delivered_count = 0
        deduplicated_count = 0
        retry_scheduled_count = 0
        failed_count = 0

        for idx, item in enumerate(batch_command.items):
            item_idem_key = item.idempotency_key
            if not item_idem_key and batch_command.batch_idempotency_prefix:
                item_idem_key = f"{batch_command.batch_idempotency_prefix}:{idx}"

            scoped_item = DeliverOutboundRecordCommand(
                tenant_id=batch_command.tenant_id,
                connection_id=batch_command.connection_id,
                stream_name=batch_command.stream_name,
                operation=item.operation,
                payload=item.payload,
                record_id=item.record_id,
                idempotency_key=item_idem_key,
                idempotency_header_name=item.idempotency_header_name,
                headers=item.headers,
                conflict_strategy=item.conflict_strategy,
                trace_id=item.trace_id,
                correlation_id=item.correlation_id,
                parent_trace_id=item.parent_trace_id,
                original_trace_id=item.original_trace_id,
                replay_count=item.replay_count,
                attempt_number=item.attempt_number,
            )
            res = await self.execute(scoped_item)
            if res.is_err or res.value is None:
                return Result.fail(
                    res.error or ConnectionNotFoundError.for_id(batch_command.connection_id)
                )

            outcome = res.value
            results.append(outcome)
            if outcome.status is OutboundDispatchStatus.DELIVERED:
                delivered_count += 1
                if outcome.was_deduplicated:
                    deduplicated_count += 1
            elif outcome.status is OutboundDispatchStatus.RETRY_SCHEDULED:
                retry_scheduled_count += 1
            else:
                failed_count += 1
                if batch_command.failure_policy is BatchFailurePolicy.HALT_ON_TERMINAL:
                    break

        return Result.ok(
            DeliverOutboundBatchResponse(
                total_count=len(batch_command.items),
                delivered_count=delivered_count,
                deduplicated_count=deduplicated_count,
                retry_scheduled_count=retry_scheduled_count,
                failed_count=failed_count,
                results=tuple(results),
            )
        )


__all__ = [
    "DeliverOutboundBatchCommand",
    "DeliverOutboundBatchResponse",
    "DeliverOutboundRecordCommand",
    "DeliverOutboundRecordResponse",
    "DeliverOutboundRecordUseCase",
    "compute_deterministic_idempotency_key",
]
