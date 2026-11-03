from __future__ import annotations

from dataclasses import dataclass

import structlog
from identity.domain.constants import UserStatusAction
from seedwork.domain.exceptions import Result

from ucp.application.use_cases._identity_error_translator import translate_identity_error
from ucp.domain.exceptions import (
    MissingIdpOrganizationError,
    TenantNotFoundError,
    UcpError,
    UcpUserNotFoundError,
)
from ucp.ports.outbound.uow_port import UcpUnitOfWorkPort

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, kw_only=True)
class ToggleUserStatusCommand:
    tenant_id: str
    user_id: str
    is_active: bool


class ToggleUserStatusUseCase:
    def __init__(self, uow: UcpUnitOfWorkPort) -> None:
        self._uow = uow

    async def execute(self, command: ToggleUserStatusCommand) -> Result[None, UcpError]:
        bound_logger = logger.bind(
            tenant_id=command.tenant_id,
            user_id=command.user_id,
            is_active=command.is_active,
        )
        bound_logger.info("toggle_user_status.started")

        async with self._uow:
            tenant = await self._uow.tenant_repo.find_by_id(command.tenant_id)
            if not tenant:
                bound_logger.error("toggle_user_status.tenant_not_found")
                return Result.fail(TenantNotFoundError.for_id(command.tenant_id))

            if not tenant.idp_tenant_id:
                bound_logger.error("toggle_user_status.missing_idp_tenant")
                return Result.fail(MissingIdpOrganizationError.for_tenant(command.tenant_id))

            user = await self._uow.user_repo.find_by_id_and_tenant(
                user_id=command.user_id, tenant_id=command.tenant_id
            )
            if not user or not user.idp_user_id:
                bound_logger.error("toggle_user_status.user_not_found")
                return Result.fail(
                    UcpUserNotFoundError.for_tenant_user(command.user_id, command.tenant_id)
                )

            action = UserStatusAction.ACTIVATE if command.is_active else UserStatusAction.DEACTIVATE
            status_res = user.change_status(action=action, tenant_id=command.tenant_id)
            if status_res.is_err:
                user_err = status_res.unwrap_err()
                bound_logger.error(
                    "toggle_user_status.conflict",
                    code=user_err.code.value,
                    reason=user_err.message,
                )
                return Result.fail(translate_identity_error(user_err))

            await self._uow.user_repo.save(user)
            await self._uow.commit()

        bound_logger.info("toggle_user_status.completed")
        return Result.ok(None)
