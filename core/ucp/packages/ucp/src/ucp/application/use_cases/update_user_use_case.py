from __future__ import annotations

from dataclasses import dataclass

import structlog
from seedwork.domain.exceptions import Result

from ucp.application.use_cases._identity_error_translator import translate_identity_error
from ucp.domain.exceptions import (
    MissingIdpOrganizationError,
    TenantNotFoundError,
    UcpError,
    UcpRoleNotFoundError,
    UcpUserNotFoundError,
)
from ucp.ports.outbound.uow_port import UcpUnitOfWorkPort

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, kw_only=True)
class UpdateUserCommand:
    tenant_id: str
    user_id: str
    first_name: str
    last_name: str
    role: str


class UpdateUserUseCase:
    def __init__(self, uow: UcpUnitOfWorkPort) -> None:
        self._uow = uow

    async def execute(self, command: UpdateUserCommand) -> Result[None, UcpError]:
        bound_logger = logger.bind(tenant_id=command.tenant_id, user_id=command.user_id)
        bound_logger.info("update_user.started", role=command.role)

        async with self._uow:
            tenant = await self._uow.tenant_repo.find_by_id(command.tenant_id)
            if not tenant:
                bound_logger.error("update_user.tenant_not_found")
                return Result.fail(TenantNotFoundError.for_id(command.tenant_id))

            if not tenant.idp_tenant_id:
                bound_logger.error("update_user.missing_idp_tenant")
                return Result.fail(MissingIdpOrganizationError.for_tenant(command.tenant_id))

            user = await self._uow.user_repo.find_by_id_and_tenant(
                user_id=command.user_id, tenant_id=command.tenant_id
            )
            if not user or not user.idp_user_id:
                bound_logger.error("update_user.user_not_found")
                return Result.fail(
                    UcpUserNotFoundError.for_tenant_user(command.user_id, command.tenant_id)
                )

            pbac_role = await self._uow.role_repo.get_by_id(command.role)
            if not pbac_role:
                bound_logger.error("update_user.role_not_found", role_id=command.role)
                return Result.fail(
                    UcpRoleNotFoundError.for_id(
                        command.role,
                        message=(
                            f"Global PBAC Role '{command.role}' is not seeded in the database."
                        ),
                    )
                )

            profile_res = user.update_profile(
                first_name=command.first_name,
                last_name=command.last_name,
                tenant_id=command.tenant_id,
                role=pbac_role.name,
            )
            if profile_res.is_err:
                user_err = profile_res.unwrap_err()
                bound_logger.error(
                    "update_user.validation_failed",
                    code=user_err.code.value,
                    reason=user_err.message,
                )
                return Result.fail(translate_identity_error(user_err))

            await self._uow.user_repo.save(user)

            await self._uow.role_repo.remove_user_roles(tenant_id=tenant.id, user_id=user.id)
            await self._uow.role_repo.assign_user_role(
                tenant_id=tenant.id, user_id=user.id, role_id=pbac_role.id
            )

            user.assign_role(role_id=pbac_role.id, role_name=pbac_role.name, tenant_id=tenant.id)
            await self._uow.user_repo.save(user)
            await self._uow.commit()

        bound_logger.info("update_user.completed")
        return Result.ok(None)
