"""Use case for synthesizing and dispatching simulated push webhook events into L1 Ingress."""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

import structlog
from ip.engine.application.use_cases.connections.get_connection_use_case import (
    GetConnectionQuery,
    GetConnectionUseCase,
)
from ip.engine.application.use_cases.ingestion.receive_push_use_case import (
    ReceivePushCommand,
    ReceivePushUseCase,
)
from ip.engine.domain.connection.enums import ConnectionStatus
from ip.engine.domain.exceptions import (
    ConnectionDeactivatedError,
    ConnectionNotFoundError,
    IpError,
    IpErrorCode,
    Result,
)
from ip.engine.ports.outbound.inbound_ack_port import InboundAckPort
from ip.engine.ports.outbound.inbound_payload_decoder_port import InboundPayloadDecoderPort
from ip.engine.ports.outbound.inbound_verifier_port import InboundVerifierPort
from ip.engine.ports.outbound.tiered_storage_port import TieredStoragePort
from ip.engine.ports.outbound.uow import (
    IpControlPlaneUnitOfWorkPort,
    IpDataPlaneUnitOfWorkProviderPort,
)
from ip.solutions.connectors.sandbox.universal.connector import UniversalSchemaSimulatorConnector
from ip.solutions.connectors.sandbox.universal.inference import parse_simulator_manifest
from ip.solutions.connectors.sandbox.universal.spec import SimulatorStreamSpec
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
    """Synthesizes fake records from the simulator entity schema and emits them into L1 `ReceivePushUseCase`."""

    def __init__(
        self,
        *,
        control_plane_uow: IpControlPlaneUnitOfWorkPort,
        data_plane_uow_provider: IpDataPlaneUnitOfWorkProviderPort,
        tiered_storage: TieredStoragePort,
        verifier: InboundVerifierPort,
        decoder: InboundPayloadDecoderPort,
        ack: InboundAckPort,
        synthesizer: JsonSchemaRecordSynthesizer | None = None,
    ) -> None:
        self._cp_uow = control_plane_uow
        self._dp_uow_provider = data_plane_uow_provider
        self._tiered_storage = tiered_storage
        self._verifier = verifier
        self._decoder = decoder
        self._ack = ack
        self._synthesizer = synthesizer or JsonSchemaRecordSynthesizer()

    async def _resolve_simulator_stream(
        self, command: TriggerSimulatedPushCommand
    ) -> Result[tuple[str, int, SimulatorStreamSpec], IpError]:
        conn_uc = GetConnectionUseCase(uow=self._cp_uow)
        conn_res = await conn_uc.execute(
            GetConnectionQuery(
                tenant_id=command.tenant_id,
                connection_id=command.connection_id,
            )
        )
        if not conn_res.success or conn_res.connection is None:
            return Result.fail(
                conn_res.error or ConnectionNotFoundError.for_id(command.connection_id)
            )

        conn = conn_res.connection
        if conn.status == ConnectionStatus.DEACTIVATED.value:
            return Result.fail(ConnectionDeactivatedError.for_id(command.connection_id))

        if conn.app_id != UniversalSchemaSimulatorConnector.APP_ID:
            return Result.fail(
                IpError(
                    code=IpErrorCode.INVALID_CONFIGURATION,
                    message=(
                        f"Connection '{command.connection_id}' (app_id='{conn.app_id}') is not a "
                        f"Universal Sandbox Simulator connection."
                    ),
                    http_status=422,
                )
            )

        manifest_res = parse_simulator_manifest(dict(conn.public_config))
        if manifest_res.is_err:
            return Result.fail(manifest_res.unwrap_err())

        manifest = manifest_res.unwrap()
        spec = manifest.streams.get(command.stream_name)
        if spec is None:
            return Result.fail(
                IpError(
                    code=IpErrorCode.STREAM_NOT_FOUND,
                    message=(
                        f"Entity '{command.stream_name}' is not configured on simulator connection "
                        f"'{command.connection_id}'."
                    ),
                    http_status=404,
                )
            )
        return Result.ok((conn.app_id, manifest.seed, spec))

    async def execute(
        self, command: TriggerSimulatedPushCommand
    ) -> Result[SimulatePushResultDTO, IpError]:
        resolved_res = await self._resolve_simulator_stream(command)
        if resolved_res.is_err:
            return Result.fail(resolved_res.unwrap_err())
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
            return Result.fail(shard_res.unwrap_err())
        shard_id, shard_dsn = shard_res.unwrap()

        ingested_record_ids: list[str] = []
        trace_ids: list[str] = []
        is_thin = command.delivery_style == SimulatedPushDeliveryStyle.THIN_PING

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
