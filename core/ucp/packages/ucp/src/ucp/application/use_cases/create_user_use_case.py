from __future__ import annotations

from dataclasses import dataclass

import structlog
from identity.domain.user import User
from seedwork.domain.exceptions import Result
from seedwork.utils import generate_id

from ucp.application.use_cases._identity_error_translator import translate_identity_error
from ucp.domain.exceptions import (
    MissingIdpOrganizationError,
    TenantNotFoundError,
    UcpError,
    UcpRoleNotFoundError,
)
from ucp.ports.outbound.uow_port import UcpUnitOfWorkPort

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, kw_only=True)
class CreateUserCommand:
    tenant_id: str
    email: str
    first_name: str
    last_name: str
    role: str


class CreateUserUseCase:
    def __init__(self, uow: UcpUnitOfWorkPort) -> None:
        self._uow = uow

    async def execute(self, command: CreateUserCommand) -> Result[str, UcpError]:
        logger.info(
            "create_user.started",
            tenant_id=command.tenant_id,
            role=command.role,
        )
        async with self._uow:
            tenant = await self._uow.tenant_repo.find_by_id(command.tenant_id)
            if not tenant:
                logger.error("create_user.tenant_not_found", tenant_id=command.tenant_id)
                return Result.fail(TenantNotFoundError.for_id(command.tenant_id))

            if not tenant.idp_tenant_id:
                logger.error("create_user.missing_idp_tenant", tenant_id=command.tenant_id)
                return Result.fail(MissingIdpOrganizationError.for_tenant(command.tenant_id))

            pbac_role = await self._uow.role_repo.get_platform_role_by_id(command.role)
            if not pbac_role:
                logger.error(
                    "create_user.role_not_found",
                    tenant_id=command.tenant_id,
                    role_id=command.role,
                )
                return Result.fail(
                    UcpRoleNotFoundError.for_id(
                        command.role,
                        message=f"Global PBAC Role '{command.role}' is not found in the database.",
                    )
                )

            local_user_id = generate_id(User.ID_PREFIX)
            name = f"{command.first_name} {command.last_name}".strip()

            user_res = User.create(
                id=local_user_id,
                idp_user_id=None,
                email=command.email,
                name=name,
            )
            if user_res.is_err:
                user_err = user_res.unwrap_err()
                logger.error(
                    "create_user.validation_failed",
                    tenant_id=command.tenant_id,
                    code=user_err.code.value,
                    reason=user_err.message,
                )
                return Result.fail(translate_identity_error(user_err))

            new_user = user_res.unwrap()
            await self._uow.user_repo.save(new_user)

            await self._uow.role_repo.assign_user_role(
                tenant_id=tenant.id, user_id=local_user_id, role_id=pbac_role.id
            )

            new_user.record_invitation(
                tenant_id=tenant.id,
                first_name=command.first_name,
                last_name=command.last_name,
                role=pbac_role.name,
            )
            await self._uow.user_repo.save(new_user)
            await self._uow.commit()

        logger.info(
            "create_user.completed",
            tenant_id=tenant.id,
            user_id=local_user_id,
        )
        return Result.ok(local_user_id)
