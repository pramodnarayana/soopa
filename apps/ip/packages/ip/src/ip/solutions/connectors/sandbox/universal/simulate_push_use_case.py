"""Use case for synthesizing and dispatching simulated push webhook events into L1 Ingress."""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

import structlog
from ip.engine.application.use_cases.connections.token_manager_service import (
    GetValidCredentialsCommand,
    TokenManagerService,
)
from ip.engine.application.use_cases.ingestion.receive_push_use_case import (
    ReceivePushCommand,
    ReceivePushUseCase,
)
from ip.engine.domain.exceptions import (
    IpError,
    IpErrorCode,
    Result,
)
from ip.engine.ports.outbound.inbound_ack_port import InboundAckPort
from ip.engine.ports.outbound.inbound_payload_decoder_port import InboundPayloadDecoderPort
from ip.engine.ports.outbound.inbound_verifier_port import InboundVerifierPort
from ip.engine.ports.outbound.tiered_storage_port import TieredStoragePort
from ip.engine.ports.outbound.uow import IpDataPlaneUnitOfWorkProviderPort
from ip.solutions.connectors.sandbox.universal.dto import entity_dto_to_stream_spec
from ip.solutions.connectors.sandbox.universal.inference import (
    parse_simulator_connection_config,
)
from ip.solutions.connectors.sandbox.universal.ports import SimulatorSandboxReaderPort
from ip.solutions.connectors.sandbox.universal.spec import (
    UNIVERSAL_SIMULATOR_APP_ID,
    SimulatorStreamSpec,
)
from ip.solutions.connectors.sandbox.universal.synthesizer import JsonSchemaRecordSynthesizer

logger = structlog.get_logger(__name__)


class SimulatedPushDeliveryStyle(StrEnum):
    """Webhook payload delivery style for simulated push notifications."""

    FULL_PAYLOAD = "FULL_PAYLOAD"
    THIN_PING = "THIN_PING"


@dataclass(frozen=True)
class TriggerSimulatedPushCommand:
    """Command to synthesize and push N records for a simulator entity stream into L1 Ingress."""

    tenant_id: str
    connection_id: str
    stream_name: str
    count: int = 5
    delivery_style: SimulatedPushDeliveryStyle = SimulatedPushDeliveryStyle.FULL_PAYLOAD
    correlation_id: str | None = None


@dataclass(frozen=True)
class SimulatePushResultDTO:
    """Outcome of a simulated push webhook emission."""

    connection_id: str
    stream_name: str
    records_pushed: int
    record_ids: Sequence[str] = field(default_factory=tuple)
    trace_ids: Sequence[str] = field(default_factory=tuple)


class TriggerSimulatedPushUseCase:
    """Authenticates a Virtual Sandbox connection, synthesizes fake records, and emits them into L1 `ReceivePushUseCase`."""

    def __init__(
        self,
        *,
        data_plane_uow_provider: IpDataPlaneUnitOfWorkProviderPort,
        tiered_storage: TieredStoragePort,
        verifier: InboundVerifierPort,
        decoder: InboundPayloadDecoderPort,
        ack: InboundAckPort,
        sandbox_reader: SimulatorSandboxReaderPort,
        token_manager: TokenManagerService,
        synthesizer: JsonSchemaRecordSynthesizer | None = None,
    ) -> None:
        self._dp_uow_provider = data_plane_uow_provider
        self._tiered_storage = tiered_storage
        self._verifier = verifier
        self._decoder = decoder
        self._ack = ack
        self._sandbox_reader = sandbox_reader
        self._token_manager = token_manager
        self._synthesizer = synthesizer or JsonSchemaRecordSynthesizer()

    async def _resolve_simulator_stream(
        self, command: TriggerSimulatedPushCommand
    ) -> Result[tuple[str, int, SimulatorStreamSpec], IpError]:
        creds_res = await self._token_manager.get_valid_credentials(
            GetValidCredentialsCommand(
                tenant_id=command.tenant_id,
                connection_id=command.connection_id,
            )
        )
        if creds_res.is_err:
            return Result.fail(creds_res.unwrap_err())

        resolved = creds_res.unwrap()
        if resolved.app_id != UNIVERSAL_SIMULATOR_APP_ID:
            return Result.fail(
                IpError(
                    code=IpErrorCode.INVALID_CONFIGURATION,
                    message=(
                        f"Connection '{command.connection_id}' (app_id='{resolved.app_id}') is not a "
                        f"Universal Sandbox Simulator connection."
                    ),
                    http_status=422,
                )
            )

        cfg = parse_simulator_connection_config(dict(resolved.public_config))
        raw_api_key = str(resolved.credentials.get("api_key") or "")
        auth_res = await self._sandbox_reader.authenticate_sandbox(
            sandbox_id=cfg.sandbox_id,
            raw_api_key=raw_api_key,
        )
        if auth_res.is_err:
            return Result.fail(auth_res.unwrap_err())

        sandbox = auth_res.unwrap()
        entity = await self._sandbox_reader.get_entity_by_name(sandbox.id, command.stream_name)
        if entity is None:
            return Result.fail(
                IpError(
                    code=IpErrorCode.STREAM_NOT_FOUND,
                    message=(
                        f"Entity '{command.stream_name}' is not configured in Virtual Sandbox "
                        f"'{sandbox.id}'."
                    ),
                    http_status=404,
                )
            )
        return Result.ok((resolved.app_id, cfg.seed, entity_dto_to_stream_spec(entity)))

    async def execute(
        self, command: TriggerSimulatedPushCommand
    ) -> Result[SimulatePushResultDTO, IpError]:
        resolved_res = await self._resolve_simulator_stream(command)
        if resolved_res.is_err:
            err = resolved_res.unwrap_err()
            logger.error(
                "universal_simulator_push_resolution_failed",
                tenant_id=command.tenant_id,
                connection_id=command.connection_id,
                stream_name=command.stream_name,
                error_code=err.code.value,
            )
            return Result.fail(err)
        app_id, seed, spec = resolved_res.unwrap()

        bounded_count = max(1, min(command.count, 100))
        now_iso = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        nonce_offset = (int.from_bytes(os.urandom(2), "big") % 50_000) + 1
        synthesized = self._synthesizer.synthesize_batch(
            spec,
            seed=seed,
            cursor=now_iso,
            limit=bounded_count,
            sequence_offset=nonce_offset,
        )

        shard_res = await self._dp_uow_provider.resolve_shard_info(command.tenant_id)
        if shard_res.is_err:
            shard_err = shard_res.unwrap_err()
            logger.error(
                "universal_simulator_push_shard_resolution_failed",
                tenant_id=command.tenant_id,
                connection_id=command.connection_id,
                error_code=shard_err.code.value,
            )
            return Result.fail(shard_err)
        shard_id, shard_dsn = shard_res.unwrap()

        ingested_record_ids: list[str] = []
        trace_ids: list[str] = []
        is_thin = command.delivery_style == SimulatedPushDeliveryStyle.THIN_PING

        async with self._dp_uow_provider.get_data_plane_uow(
            tenant_id=command.tenant_id,
            shard_id=shard_id,
            shard_dsn=shard_dsn,
        ) as dp_uow:
            push_uc = ReceivePushUseCase(
                uow=dp_uow,
                tiered_storage=self._tiered_storage,
                verifier=self._verifier,
                decoder=self._decoder,
                ack=self._ack,
            )
            for env in synthesized:
                wire_payload = (
                    {
                        "event": f"{command.stream_name}.updated",
                        "record_id": env.record_id,
                        "emitted_at": env.emitted_at,
                    }
                    if is_thin
                    else env.data
                )
                raw_bytes = json.dumps(wire_payload).encode("utf-8")
                push_res = await push_uc.execute(
                    ReceivePushCommand(
                        tenant_id=command.tenant_id,
                        connection_id=command.connection_id,
                        app_id=app_id,
                        stream_name=command.stream_name,
                        raw_payload=raw_bytes,
                        headers={"content-type": "application/json"},
                        external_event_id=f"sim_push_{env.record_id}_{os.urandom(4).hex()}",
                        is_thin=is_thin,
                        thin_record_id=env.record_id if is_thin else None,
                        correlation_id=command.correlation_id,
                    )
                )
                if push_res.status_code >= 400:
                    logger.error(
                        "universal_simulator_push_ingress_rejected",
                        tenant_id=command.tenant_id,
                        connection_id=command.connection_id,
                        stream_name=command.stream_name,
                        status_code=push_res.status_code,
                    )
                    return Result.fail(
                        IpError(
                            code=IpErrorCode.INBOUND_VERIFICATION_FAILED,
                            message=f"Simulated push rejected by L1 Ingress (HTTP {push_res.status_code}).",
                            http_status=push_res.status_code,
                        )
                    )
                if push_res.record_id:
                    ingested_record_ids.append(push_res.record_id)
                if push_res.trace_id:
                    trace_ids.append(push_res.trace_id)

        logger.info(
            "universal_simulator_push_emitted",
            tenant_id=command.tenant_id,
            connection_id=command.connection_id,
            stream_name=command.stream_name,
            delivery_style=command.delivery_style.value,
            records_pushed=len(ingested_record_ids),
        )
        return Result.ok(
            SimulatePushResultDTO(
                connection_id=command.connection_id,
                stream_name=command.stream_name,
                records_pushed=len(ingested_record_ids),
                record_ids=tuple(ingested_record_ids),
                trace_ids=tuple(trace_ids),
            )
        )


__all__ = [
    "SimulatePushResultDTO",
    "SimulatedPushDeliveryStyle",
    "TriggerSimulatedPushCommand",
    "TriggerSimulatedPushUseCase",
]
