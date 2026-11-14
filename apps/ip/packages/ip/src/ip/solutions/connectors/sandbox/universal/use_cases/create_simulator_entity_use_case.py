"""Use case to create a validated Simulator Entity (`ip.simulator_entities`) for a Simulator Connection."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from ip.engine.domain.exceptions import IpError, Result
from ip.engine.ports.outbound.connection_repository_port import ConnectionRepositoryPort
from ip.solutions.connectors.sandbox.universal.cadence import validate_push_cadence_config
from ip.solutions.connectors.sandbox.universal.chaos import SimulatorChaosPolicy
from ip.solutions.connectors.sandbox.universal.dto import (
    SIMULATOR_ENTITY_ID_PREFIX,
    SimulatorEntityDTO,
)
from ip.solutions.connectors.sandbox.universal.inference import (
    build_validated_entity_blueprint,
)
from ip.solutions.connectors.sandbox.universal.ports import (
    SimulatorEntityQuotaExceededError,
    SimulatorUnitOfWorkPort,
)
from ip.solutions.connectors.sandbox.universal.spec import (
    DEFAULT_SIMULATOR_CURSOR_STEP_SECONDS,
    DEFAULT_SIMULATOR_RECORDS_PER_PULL,
    MAX_SIMULATOR_ENTITIES_PER_CONNECTION,
    PushCadenceMode,
    StreamVelocityMode,
)
from ip.solutions.connectors.sandbox.universal.use_cases.connection_guard import (
    lock_simulator_connection,
    validate_simulator_entity_bounds,
)
from seedwork.domain.types import JsonDict, JsonValue
from seedwork.utils import generate_id

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class CreateSimulatorEntityCommand:
    """Command to create and validate a new entity inside a Simulator connection."""

    tenant_id: str
    connection_id: str
    entity_name: str
    sample_blueprint: JsonValue
    primary_key_field: str | None = None
    cursor_field: str | None = None
    push_mode: PushCadenceMode = PushCadenceMode.RANDOM_BURST
    push_config: Mapping[str, JsonValue] | None = None
    records_per_pull: int = DEFAULT_SIMULATOR_RECORDS_PER_PULL
    cursor_step_seconds: int = DEFAULT_SIMULATOR_CURSOR_STEP_SECONDS
    velocity_mode: StreamVelocityMode = StreamVelocityMode.ENTITY_TRANSACTIONAL
    chaos_policy: Mapping[str, JsonValue] | None = None


class CreateSimulatorEntityUseCase:
    """Validates blueprint & schema inference at write time and persists `SimulatorEntityDTO` under a UoW row lock."""

    def __init__(
        self,
        *,
        uow: SimulatorUnitOfWorkPort,
        connections: ConnectionRepositoryPort,
    ) -> None:
        self._uow = uow
        self._connections = connections

    async def execute(
        self, command: CreateSimulatorEntityCommand
    ) -> Result[SimulatorEntityDTO, IpError]:
        tenant_id = command.tenant_id.strip()
        connection_id = command.connection_id.strip()

        bounds_err = validate_simulator_entity_bounds(
            records_per_pull=command.records_per_pull,
            cursor_step_seconds=command.cursor_step_seconds,
        )
        if bounds_err is not None:
            return Result.fail(bounds_err)

        cadence_err = validate_push_cadence_config(command.push_mode, command.push_config)
        if cadence_err is not None:
            return Result.fail(cadence_err)

        validated_res = build_validated_entity_blueprint(
            entity_name=command.entity_name,
            sample_blueprint=command.sample_blueprint,
            primary_key_field=command.primary_key_field,
            cursor_field=command.cursor_field,
        )
        if validated_res.is_err:
            val_err = validated_res.unwrap_err()
            logger.error(
                "simulator_entity_blueprint_validation_failed",
                tenant_id=tenant_id,
                connection_id=connection_id,
                entity_name=command.entity_name,
                error_code=val_err.code.value,
            )
            return Result.fail(val_err)
        validated = validated_res.unwrap()

        chaos_dict: JsonDict = SimulatorChaosPolicy.from_mapping(command.chaos_policy).to_dict()
        now = datetime.now(UTC)
        entity_dto = SimulatorEntityDTO(
            id=generate_id(SIMULATOR_ENTITY_ID_PREFIX),
            tenant_id=tenant_id,
            connection_id=connection_id,
            entity_name=validated.entity_name,
            primary_key_field=validated.primary_key_field,
            cursor_field=validated.cursor_field,
            push_mode=command.push_mode,
            push_config=dict(command.push_config or {}),
            records_per_pull=command.records_per_pull,
            cursor_step_seconds=command.cursor_step_seconds,
            velocity_mode=command.velocity_mode,
            sample_blueprint=validated.sample_blueprint,
            inferred_json_schema=validated.inferred_json_schema,
            chaos_policy=chaos_dict,
            version=1,
            created_at=now,
            updated_at=now,
        )

        async with self._uow:
            conn_res = await lock_simulator_connection(
                self._connections,
                tenant_id=tenant_id,
                connection_id=connection_id,
            )
            if conn_res.is_err:
                conn_err = conn_res.unwrap_err()
                logger.error(
                    "simulator_entity_create_connection_invalid",
                    tenant_id=tenant_id,
                    connection_id=connection_id,
                    error_code=conn_err.code.value,
                )
                return Result.fail(conn_err)

            existing_count = await self._uow.entities.count_entities_by_connection(
                tenant_id, connection_id
            )
            if existing_count >= MAX_SIMULATOR_ENTITIES_PER_CONNECTION:
                quota_err = SimulatorEntityQuotaExceededError.for_connection(
                    connection_id, MAX_SIMULATOR_ENTITIES_PER_CONNECTION
                )
                logger.error(
                    "simulator_entity_quota_exceeded",
                    tenant_id=tenant_id,
                    connection_id=connection_id,
                    existing_count=existing_count,
                )
                return Result.fail(quota_err)

            save_res = await self._uow.entities.create_entity(entity_dto)
            if save_res.is_err:
                save_err = save_res.unwrap_err()
                logger.error(
                    "simulator_entity_create_conflict",
                    tenant_id=tenant_id,
                    connection_id=connection_id,
                    entity_name=validated.entity_name,
                    error_code=save_err.code.value,
                )
                return Result.fail(save_err)

            await self._uow.commit()

        saved = save_res.unwrap()
        logger.info(
            "simulator_entity_created",
            tenant_id=tenant_id,
            connection_id=connection_id,
            entity_id=saved.id,
            entity_name=saved.entity_name,
        )
        return Result.ok(saved)


__all__ = ["CreateSimulatorEntityCommand", "CreateSimulatorEntityUseCase"]
