from __future__ import annotations

from dataclasses import dataclass

import structlog
from seedwork.domain.exceptions import Result

from ucp.domain.exceptions import (
    UcpError,
    UcpRoleNotFoundError,
    UcpUserNotFoundError,
    UcpValidationError,
)
from ucp.ports.outbound.uow_port import UcpUnitOfWorkPort


@dataclass(frozen=True, kw_only=True)
class AssignUserRoleCommand:
    user_id: str
    role_id: str


logger = structlog.get_logger(__name__)


class AssignUserRoleUseCase:
    """Assigns a role to a user within a tenant."""

    def __init__(self, uow: UcpUnitOfWorkPort) -> None:
        self.uow = uow

    async def execute(
        self, tenant_id: str | None, request: AssignUserRoleCommand
    ) -> Result[None, UcpError]:
        bound_logger = logger.bind(
            tenant_id=tenant_id, user_id=request.user_id, role_id=request.role_id
        )
        bound_logger.info("assign_user_role.started")

        if not tenant_id:
            bound_logger.error("assign_user_role.missing_tenant_id")
            return Result.fail(
                UcpValidationError.with_message("Role assignment requires a valid tenant ID.")
            )

        async with self.uow:
            user = await self.uow.user_repo.find_by_id_and_tenant(request.user_id, tenant_id)
            if not user:
                bound_logger.error("assign_user_role.user_not_found")
                return Result.fail(UcpUserNotFoundError.for_tenant_user(request.user_id, tenant_id))

            role = await self.uow.role_repo.get_by_id(request.role_id)
            if not role:
                bound_logger.error("assign_user_role.role_not_found")
                return Result.fail(UcpRoleNotFoundError.for_id(request.role_id))

            if role.tenant_id is not None and role.tenant_id != tenant_id:
                bound_logger.error(
                    "assign_user_role.role_tenant_mismatch",
                    role_tenant_id=role.tenant_id,
                )
                return Result.fail(
                    UcpRoleNotFoundError.for_id(
                        request.role_id,
                        message=(
                            f"Role '{request.role_id}' is scoped to tenant '{role.tenant_id}' "
                            f"and cannot be assigned in tenant '{tenant_id}'."
                        ),
                    )
                )

            user.assign_role(role_id=role.id, role_name=role.name, tenant_id=tenant_id)

            await self.uow.role_repo.assign_user_role(
                tenant_id=tenant_id,
                user_id=user.id,
                role_id=role.id,
            )

            await self.uow.user_repo.save(user)
            await self.uow.commit()

        bound_logger.info("assign_user_role.completed")
        return Result.ok(None)
