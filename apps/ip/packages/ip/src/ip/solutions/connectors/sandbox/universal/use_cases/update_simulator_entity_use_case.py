"""Use case to update an existing Simulator Entity inside a Virtual Sandbox."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from ip.engine.domain.exceptions import InvalidConnectionConfigError, IpError, Result
from ip.solutions.connectors.sandbox.universal.chaos import SimulatorChaosPolicy
from ip.solutions.connectors.sandbox.universal.dto import SimulatorEntityDTO
from ip.solutions.connectors.sandbox.universal.inference import (
    build_validated_entity_blueprint,
)
from ip.solutions.connectors.sandbox.universal.ports import (
    SimulatorEntityNotFoundError,
    SimulatorSandboxNotFoundError,
    SimulatorUnitOfWorkPort,
)
from ip.solutions.connectors.sandbox.universal.spec import StreamVelocityMode
from seedwork.domain.types import JsonValue

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class UpdateSimulatorEntityCommand:
    """Command to update fields, blueprint, or chaos policy on an existing Simulator Entity."""

    tenant_id: str
    sandbox_id: str
    entity_id: str
    entity_name: str | None = None
    sample_blueprint: JsonValue | None = None
    primary_key_field: str | None = None
    cursor_field: str | None = None
    records_per_pull: int | None = None
    cursor_step_seconds: int | None = None
    velocity_mode: StreamVelocityMode | None = None
    chaos_policy: Mapping[str, JsonValue] | None = None


class UpdateSimulatorEntityUseCase:
    """Re-infers JSON Schema on blueprint/key updates, increments `version`, and commits atomically."""

    def __init__(self, *, uow: SimulatorUnitOfWorkPort) -> None:
        self._uow = uow

    async def execute(
        self, command: UpdateSimulatorEntityCommand
    ) -> Result[SimulatorEntityDTO, IpError]:
        tenant_id = command.tenant_id.strip()
        sandbox_id = command.sandbox_id.strip()
        entity_id = command.entity_id.strip()

        async with self._uow:
            sandbox = await self._uow.sandboxes.get_sandbox_by_id_for_update(tenant_id, sandbox_id)
            if sandbox is None:
                sbx_err = SimulatorSandboxNotFoundError.for_id(command.sandbox_id)
                logger.error(
                    "simulator_entity_update_sandbox_not_found",
                    tenant_id=tenant_id,
                    sandbox_id=sandbox_id,
                    error_code=sbx_err.code.value,
                )
                return Result.fail(sbx_err)

            existing = await self._uow.sandboxes.get_entity_by_id(sandbox_id, entity_id)
            if existing is None:
                not_found = SimulatorEntityNotFoundError.for_id(sandbox_id, entity_id)
                logger.error(
                    "simulator_entity_update_not_found",
                    tenant_id=tenant_id,
                    sandbox_id=sandbox_id,
                    entity_id=entity_id,
                    error_code=not_found.code.value,
                )
                return Result.fail(not_found)

            next_records_per_pull = (
                command.records_per_pull
                if command.records_per_pull is not None
                else existing.records_per_pull
            )
            next_cursor_step = (
                command.cursor_step_seconds
                if command.cursor_step_seconds is not None
                else existing.cursor_step_seconds
            )
            if next_records_per_pull < 1 or next_records_per_pull > 5000:
                return Result.fail(
                    InvalidConnectionConfigError(
                        field_name="records_per_pull",
                        message="records_per_pull must be between 1 and 5000.",
                        details={"field": "records_per_pull"},
                    )
                )
            if next_cursor_step < 1 or next_cursor_step > 86400:
                return Result.fail(
                    InvalidConnectionConfigError(
                        field_name="cursor_step_seconds",
                        message="cursor_step_seconds must be between 1 and 86400.",
                        details={"field": "cursor_step_seconds"},
                    )
                )

            target_name = (
                command.entity_name if command.entity_name is not None else existing.entity_name
            )
            target_blueprint = (
                command.sample_blueprint
                if command.sample_blueprint is not None
                else existing.sample_blueprint
            )
            target_pk = (
                command.primary_key_field
                if command.primary_key_field is not None
                else existing.primary_key_field
            )
            target_cursor = (
                command.cursor_field if command.cursor_field is not None else existing.cursor_field
            )

            validated_res = build_validated_entity_blueprint(
                entity_name=target_name,
                sample_blueprint=target_blueprint,
                primary_key_field=target_pk,
                cursor_field=target_cursor,
            )
            if validated_res.is_err:
                val_err = validated_res.unwrap_err()
                logger.error(
                    "simulator_entity_update_validation_failed",
                    tenant_id=tenant_id,
                    sandbox_id=sandbox_id,
                    entity_id=entity_id,
                    error_code=val_err.code.value,
                )
                return Result.fail(val_err)
            validated = validated_res.unwrap()

            next_chaos = (
                SimulatorChaosPolicy.from_mapping(command.chaos_policy).to_dict()
                if command.chaos_policy is not None
                else dict(existing.chaos_policy)
            )
            updated_dto = SimulatorEntityDTO(
                id=existing.id,
                tenant_id=existing.tenant_id,
                sandbox_id=existing.sandbox_id,
                entity_name=validated.entity_name,
                primary_key_field=validated.primary_key_field,
                cursor_field=validated.cursor_field,
                records_per_pull=next_records_per_pull,
                cursor_step_seconds=next_cursor_step,
                velocity_mode=(
                    command.velocity_mode
                    if command.velocity_mode is not None
                    else existing.velocity_mode
                ),
                sample_blueprint=validated.sample_blueprint,
                inferred_json_schema=validated.inferred_json_schema,
                chaos_policy=next_chaos,
                version=existing.version + 1,
                created_at=existing.created_at,
                updated_at=datetime.now(UTC),
            )
            save_res = await self._uow.sandboxes.update_entity(updated_dto)
            if save_res.is_err:
                save_err = save_res.unwrap_err()
                logger.error(
                    "simulator_entity_update_conflict",
                    tenant_id=tenant_id,
                    sandbox_id=sandbox_id,
                    entity_id=entity_id,
                    error_code=save_err.code.value,
                )
                return Result.fail(save_err)

            await self._uow.commit()

        saved = save_res.unwrap()
        logger.info(
            "simulator_entity_updated",
            tenant_id=tenant_id,
            sandbox_id=sandbox_id,
            entity_id=saved.id,
            version=saved.version,
        )
        return Result.ok(saved)


__all__ = ["UpdateSimulatorEntityCommand", "UpdateSimulatorEntityUseCase"]
