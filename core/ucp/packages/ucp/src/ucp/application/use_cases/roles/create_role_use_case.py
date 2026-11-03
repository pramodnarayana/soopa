from __future__ import annotations

from dataclasses import dataclass

import structlog
from identity.domain.authorization import Capability, Role
from seedwork import generate_id
from seedwork.domain.exceptions import Result

from ucp.domain.constants import UcpIdPrefix
from ucp.domain.exceptions import InvalidCapabilityValueError, UcpError, UcpValidationError
from ucp.ports.outbound.uow_port import UcpUnitOfWorkPort


@dataclass(frozen=True, kw_only=True)
class CreateRoleCommand:
    name: str
    capabilities: tuple[str, ...]
    description: str | None = None


@dataclass(frozen=True, kw_only=True)
class CreateRoleResponse:
    id: str
    name: str
    capabilities: list[str]


logger = structlog.get_logger(__name__)


class CreateRoleUseCase:
    """Creates a new custom role within a tenant."""

    def __init__(self, uow: UcpUnitOfWorkPort) -> None:
        self.uow = uow

    async def execute(
        self, tenant_id: str | None, request: CreateRoleCommand
    ) -> Result[CreateRoleResponse, UcpError]:
        bound_logger = logger.bind(tenant_id=tenant_id, role_name=request.name)
        bound_logger.info("create_role.started")

        if not request.name or not request.name.strip():
            bound_logger.error("create_role.empty_name")
            return Result.fail(UcpValidationError.with_message("Role name cannot be empty."))

        valid_capabilities = {cap.value for cap in Capability}
        for cap in request.capabilities:
            if cap not in valid_capabilities:
                bound_logger.error("create_role.invalid_capability", capability=cap)
                return Result.fail(InvalidCapabilityValueError.for_capability(cap))

        async with self.uow:
            role = Role.create(
                id=generate_id(UcpIdPrefix.ROLE.value),
                tenant_id=tenant_id,
                name=request.name.strip(),
                description=request.description,
                capabilities=list(request.capabilities),
            )
            await self.uow.role_repo.save(role)
            await self.uow.commit()

        bound_logger.info("create_role.completed", role_id=role.id)
        return Result.ok(
            CreateRoleResponse(
                id=role.id,
                name=role.name,
                capabilities=role.capabilities,
            )
        )
