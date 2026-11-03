from __future__ import annotations

from dataclasses import dataclass

import structlog
from seedwork.domain.exceptions import Result

from ucp.application.use_cases._identity_error_translator import translate_identity_error
from ucp.domain.exceptions import UcpError, UcpUserNotFoundError
from ucp.ports.outbound.uow_port import UcpUnitOfWorkPort

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, kw_only=True)
class DeleteUserCommand:
    tenant_id: str
    user_id: str


class DeleteUserUseCase:
    def __init__(self, uow: UcpUnitOfWorkPort) -> None:
        self._uow = uow

    async def execute(self, command: DeleteUserCommand) -> Result[None, UcpError]:
        bound_logger = logger.bind(tenant_id=command.tenant_id, user_id=command.user_id)
        bound_logger.info("delete_user.started")

        async with self._uow:
            user = await self._uow.user_repo.find_by_id_and_tenant(
                command.user_id, command.tenant_id
            )
            if not user or not user.idp_user_id:
                bound_logger.error("delete_user.user_not_found")
                return Result.fail(
                    UcpUserNotFoundError.for_tenant_user(command.user_id, command.tenant_id)
                )

            user.remove_membership(command.tenant_id)

            await self._uow.role_repo.remove_user_roles(
                tenant_id=command.tenant_id, user_id=user.id
            )
            await self._uow.user_repo.save(user)

            has_memberships = await self._uow.role_repo.has_any_tenant_memberships(user.id)
            if not has_memberships:
                del_res = user.mark_deleted()
                if del_res.is_err:
                    user_err = del_res.unwrap_err()
                    bound_logger.error(
                        "delete_user.conflict",
                        code=user_err.code.value,
                        reason=user_err.message,
                    )
                    return Result.fail(translate_identity_error(user_err))
                await self._uow.user_repo.delete(user)

            await self._uow.commit()

        bound_logger.info("delete_user.completed")
        return Result.ok(None)
