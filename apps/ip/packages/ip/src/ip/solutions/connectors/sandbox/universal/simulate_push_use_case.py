"""Use case for synthesizing and dispatching simulated push webhook events into L1 Ingress."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
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
    ReceivePushExecutorFactory,
)
from ip.engine.domain.exceptions import (
    IpError,
    IpErrorCode,
    Result,
)
from ip.engine.ports.outbound.uow import IpDataPlaneUnitOfWorkProviderPort
from ip.solutions.connectors.sandbox.universal.cadence import resolve_push_cadence_strategy
from ip.solutions.connectors.sandbox.universal.dto import entity_dto_to_stream_spec
from ip.solutions.connectors.sandbox.universal.inference import (
    parse_simulator_connection_config,
)
from ip.solutions.connectors.sandbox.universal.ports import SimulatorEntityReaderPort
from ip.solutions.connectors.sandbox.universal.spec import (
    DEFAULT_SIMULATED_PUSH_COUNT,
    MAX_SIMULATED_PUSH_COUNT,
    MIN_SIMULATED_PUSH_COUNT,
    SimulatorStreamSpec,
)
from ip.solutions.connectors.sandbox.universal.strategies import CadenceState, PushCadenceMode
from ip.solutions.connectors.sandbox.universal.synthesizer import JsonSchemaRecordSynthesizer
from ip.solutions.connectors.sandbox.universal.use_cases.connection_guard import (
    validate_simulator_app_id,
)
from seedwork.domain.types import JsonValue

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
    count: int = DEFAULT_SIMULATED_PUSH_COUNT
    delivery_style: SimulatedPushDeliveryStyle = SimulatedPushDeliveryStyle.FULL_PAYLOAD
    correlation_id: str | None = None
    cadence_mode: PushCadenceMode | None = None
    cadence_config: Mapping[str, JsonValue] | None = None


@dataclass(frozen=True)
class SimulatePushResultDTO:
    """Outcome of a simulated push webhook emission."""

    connection_id: str
    stream_name: str
    records_pushed: int
    record_ids: Sequence[str] = field(default_factory=tuple)
    trace_ids: Sequence[str] = field(default_factory=tuple)


class TriggerSimulatedPushUseCase:
    """Verifies a Simulator connection, synthesizes fake records from `ip.simulator_entities`, and emits them via `ReceivePushExecutorFactory`."""

    def __init__(
        self,
        *,
        data_plane_uow_provider: IpDataPlaneUnitOfWorkProviderPort,
        push_executor_factory: ReceivePushExecutorFactory,
        entity_reader: SimulatorEntityReaderPort,
        token_manager: TokenManagerService,
        synthesizer: JsonSchemaRecordSynthesizer | None = None,
    ) -> None:
        self._dp_uow_provider = data_plane_uow_provider
        self._push_executor_factory = push_executor_factory
        self._entity_reader = entity_reader
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
        app_err = validate_simulator_app_id(
            connection_id=command.connection_id,
            app_id=resolved.app_id,
        )
        if app_err is not None:
            return Result.fail(app_err)

        cfg = parse_simulator_connection_config(
            dict(resolved.public_config),
            connection_id=command.connection_id,
        )
        entity_res = await self._entity_reader.get_entity_by_name(
            command.tenant_id, command.connection_id, command.stream_name
        )
        if entity_res.is_err:
            return Result.fail(entity_res.unwrap_err())
        entity = entity_res.value
        if entity is None:
            return Result.fail(
                IpError(
                    code=IpErrorCode.STREAM_NOT_FOUND,
                    message=(
                        f"Entity '{command.stream_name}' is not configured in Simulator connection "
                        f"'{command.connection_id}'."
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

        effective_cadence_mode = command.cadence_mode or spec.push_mode
        effective_cadence_config = (
            command.cadence_config if command.cadence_config is not None else spec.push_config
        )
        is_thin = (
            command.delivery_style == SimulatedPushDeliveryStyle.THIN_PING
            or effective_cadence_mode == PushCadenceMode.THIN_PUSH
        )

        strategy = resolve_push_cadence_strategy(effective_cadence_mode, effective_cadence_config)
        now_dt = datetime.now(UTC)
        cadence_state = CadenceState(
            cycle_index=0,
            elapsed_seconds=0.0,
            total_emitted=0,
            last_emitted_at=now_dt,
        )
        if not strategy.should_emit(cadence_state):
            logger.info(
                "universal_simulator_push_emission_skipped_by_strategy",
                tenant_id=command.tenant_id,
                connection_id=command.connection_id,
                cadence_mode=effective_cadence_mode.value,
            )
            return Result.ok(
                SimulatePushResultDTO(
                    connection_id=command.connection_id,
                    stream_name=command.stream_name,
                    records_pushed=0,
                    record_ids=(),
                    trace_ids=(),
                )
            )

        if command.count != DEFAULT_SIMULATED_PUSH_COUNT:
            target_count = command.count
        else:
            target_count = strategy.compute_batch_size(cadence_state)

        bounded_count = max(MIN_SIMULATED_PUSH_COUNT, min(target_count, MAX_SIMULATED_PUSH_COUNT))
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

        async with self._dp_uow_provider.get_data_plane_uow(
            tenant_id=command.tenant_id,
            shard_id=shard_id,
            shard_dsn=shard_dsn,
        ) as dp_uow:
            push_executor = self._push_executor_factory(dp_uow)
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
                push_res = await push_executor.execute(
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
