"""Use case to create a validated Simulator Entity (`ip.simulator_entities`) inside a Virtual Sandbox."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from ip.engine.domain.exceptions import InvalidConnectionConfigError, IpError, Result
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
    SimulatorSandboxNotFoundError,
    SimulatorUnitOfWorkPort,
)
from ip.solutions.connectors.sandbox.universal.spec import (
    MAX_SIMULATOR_ENTITIES_PER_SANDBOX,
    StreamVelocityMode,
)
from seedwork.domain.types import JsonDict, JsonValue
from seedwork.utils import generate_id

logger = structlog.get_logger(__name__)


def _validate_numeric_bounds(
    *,
    records_per_pull: int,
    cursor_step_seconds: int,
) -> InvalidConnectionConfigError | None:
    if records_per_pull < 1 or records_per_pull > 5000:
        return InvalidConnectionConfigError(
            field_name="records_per_pull",
            message="records_per_pull must be between 1 and 5000.",
            details={"field": "records_per_pull"},
        )
    if cursor_step_seconds < 1 or cursor_step_seconds > 86400:
        return InvalidConnectionConfigError(
            field_name="cursor_step_seconds",
            message="cursor_step_seconds must be between 1 and 86400.",
            details={"field": "cursor_step_seconds"},
        )
    return None


@dataclass(frozen=True)
class CreateSimulatorEntityCommand:
    """Command to create and validate a new entity inside a Virtual Sandbox."""

    tenant_id: str
    sandbox_id: str
    entity_name: str
    sample_blueprint: JsonValue
    primary_key_field: str | None = None
    cursor_field: str | None = None
    records_per_pull: int = 25
    cursor_step_seconds: int = 60
    velocity_mode: StreamVelocityMode = StreamVelocityMode.ENTITY_TRANSACTIONAL
    chaos_policy: Mapping[str, JsonValue] | None = None


class CreateSimulatorEntityUseCase:
    """Validates blueprint & schema inference at write time and persists `SimulatorEntityDTO` under a UoW row lock."""

    def __init__(self, *, uow: SimulatorUnitOfWorkPort) -> None:
        self._uow = uow

    async def execute(
        self, command: CreateSimulatorEntityCommand
    ) -> Result[SimulatorEntityDTO, IpError]:
        tenant_id = command.tenant_id.strip()
        sandbox_id = command.sandbox_id.strip()

        bounds_err = _validate_numeric_bounds(
            records_per_pull=command.records_per_pull,
            cursor_step_seconds=command.cursor_step_seconds,
        )
        if bounds_err is not None:
            return Result.fail(bounds_err)

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
                sandbox_id=sandbox_id,
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
            sandbox_id=sandbox_id,
            entity_name=validated.entity_name,
            primary_key_field=validated.primary_key_field,
            cursor_field=validated.cursor_field,
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
            sandbox = await self._uow.sandboxes.get_sandbox_by_id_for_update(tenant_id, sandbox_id)
            if sandbox is None:
                err = SimulatorSandboxNotFoundError.for_id(command.sandbox_id)
                logger.error(
                    "simulator_entity_create_sandbox_not_found",
                    tenant_id=tenant_id,
                    sandbox_id=sandbox_id,
                    error_code=err.code.value,
                )
                return Result.fail(err)

            existing_count = await self._uow.sandboxes.count_entities_by_sandbox(sandbox_id)
            if existing_count >= MAX_SIMULATOR_ENTITIES_PER_SANDBOX:
                quota_err = SimulatorEntityQuotaExceededError.for_sandbox(
                    sandbox_id, MAX_SIMULATOR_ENTITIES_PER_SANDBOX
                )
                logger.error(
                    "simulator_entity_quota_exceeded",
                    tenant_id=tenant_id,
                    sandbox_id=sandbox_id,
                    existing_count=existing_count,
                )
                return Result.fail(quota_err)

            save_res = await self._uow.sandboxes.create_entity(entity_dto)
            if save_res.is_err:
                save_err = save_res.unwrap_err()
                logger.error(
                    "simulator_entity_create_conflict",
                    tenant_id=tenant_id,
                    sandbox_id=sandbox_id,
                    entity_name=validated.entity_name,
                    error_code=save_err.code.value,
                )
                return Result.fail(save_err)

            await self._uow.commit()

        saved = save_res.unwrap()
        logger.info(
            "simulator_entity_created",
            tenant_id=tenant_id,
            sandbox_id=sandbox_id,
            entity_id=saved.id,
            entity_name=saved.entity_name,
        )
        return Result.ok(saved)


__all__ = ["CreateSimulatorEntityCommand", "CreateSimulatorEntityUseCase"]
