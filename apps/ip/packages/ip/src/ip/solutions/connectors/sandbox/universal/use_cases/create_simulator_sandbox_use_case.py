"""Use case to provision a new Virtual Sandbox (`ip.simulator_sandboxes`) with a hashed API key."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from ip.engine.domain.exceptions import InvalidConnectionConfigError, IpError, Result
from ip.solutions.connectors.sandbox.universal.dto import (
    SIMULATOR_SANDBOX_ID_PREFIX,
    SimulatorSandboxDTO,
    generate_sandbox_api_key,
)
from ip.solutions.connectors.sandbox.universal.ports import SimulatorUnitOfWorkPort
from seedwork.utils import generate_id

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class CreateSimulatorSandboxCommand:
    """Command to create an isolated Virtual Sandbox environment for a tenant."""

    tenant_id: str
    name: str


@dataclass(frozen=True)
class CreateSimulatorSandboxResult:
    """Co-located CQRS result containing the persisted sandbox DTO and one-time plaintext `api_key`."""

    sandbox: SimulatorSandboxDTO
    api_key: str


class CreateSimulatorSandboxUseCase:
    """Creates a `SimulatorSandboxDTO`, hashes its one-time `api_key`, and commits atomically via `SimulatorUnitOfWorkPort`."""

    def __init__(self, *, uow: SimulatorUnitOfWorkPort) -> None:
        self._uow = uow

    async def execute(
        self, command: CreateSimulatorSandboxCommand
    ) -> Result[CreateSimulatorSandboxResult, IpError]:
        tenant_id = command.tenant_id.strip()
        if not tenant_id:
            return Result.fail(
                InvalidConnectionConfigError(
                    field_name="tenant_id",
                    message="tenant_id cannot be empty.",
                    details={"field": "tenant_id"},
                )
            )
        cleaned_name = command.name.strip()
        if not cleaned_name or len(cleaned_name) > 255:
            return Result.fail(
                InvalidConnectionConfigError(
                    field_name="name",
                    message="Virtual sandbox name must be between 1 and 255 characters.",
                    details={"field": "name"},
                )
            )

        raw_api_key, key_hash, key_prefix = generate_sandbox_api_key()
        now = datetime.now(UTC)
        sandbox_dto = SimulatorSandboxDTO(
            id=generate_id(SIMULATOR_SANDBOX_ID_PREFIX),
            tenant_id=tenant_id,
            name=cleaned_name,
            api_key_hash=key_hash,
            api_key_prefix=key_prefix,
            created_at=now,
            updated_at=now,
        )
        async with self._uow:
            save_res = await self._uow.sandboxes.create_sandbox(sandbox_dto)
            if save_res.is_err:
                err = save_res.unwrap_err()
                logger.error(
                    "simulator_sandbox_create_failed",
                    tenant_id=tenant_id,
                    name=cleaned_name,
                    error_code=err.code.value,
                )
                return Result.fail(err)
            await self._uow.commit()

        saved = save_res.unwrap()
        logger.info(
            "simulator_sandbox_created",
            tenant_id=tenant_id,
            sandbox_id=saved.id,
            name=saved.name,
        )
        return Result.ok(CreateSimulatorSandboxResult(sandbox=saved, api_key=raw_api_key))


__all__ = [
    "CreateSimulatorSandboxCommand",
    "CreateSimulatorSandboxResult",
    "CreateSimulatorSandboxUseCase",
]
