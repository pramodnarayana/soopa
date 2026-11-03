from __future__ import annotations

import structlog
from seedwork.domain.exceptions import Result

from ucp.application.use_cases._identity_error_translator import translate_identity_error
from ucp.domain.exceptions import TenantNotFoundError, UcpError
from ucp.ports.outbound.uow_port import UcpUnitOfWorkPort

logger = structlog.get_logger(__name__)


class DeleteTenantUseCase:
    def __init__(self, uow: UcpUnitOfWorkPort) -> None:
        self.uow = uow

    async def execute(
        self, tenant_id: str, idempotency_key: str | None = None
    ) -> Result[None, UcpError]:
        bound_logger = logger.bind(tenant_id=tenant_id)
        bound_logger.info("delete_tenant.started", idempotency_key=idempotency_key)

        async with self.uow:
            tenant = await self.uow.tenant_repo.find_by_id(tenant_id)
            if not tenant:
                bound_logger.error("delete_tenant.not_found")
                return Result.fail(TenantNotFoundError.for_id(tenant_id))

            tenant_users = await self.uow.user_repo.find_users_by_tenant(tenant_id)

            del_tenant_res = tenant.mark_deleted()
            if del_tenant_res.is_err:
                err = del_tenant_res.unwrap_err()
                bound_logger.error(
                    "delete_tenant.conflict",
                    code=err.code.value,
                    reason=err.message,
                )
                return Result.fail(err)

            await self.uow.tenant_repo.delete(tenant, idempotency_key)

            for user in tenant_users:
                has_memberships = await self.uow.user_repo.has_any_tenant_memberships(user.id)
                if not has_memberships:
                    del_user_res = user.mark_deleted()
                    if del_user_res.is_err:
                        user_err = del_user_res.unwrap_err()
                        bound_logger.error(
                            "delete_tenant.orphan_user_delete_conflict",
                            user_id=user.id,
                            code=user_err.code.value,
                            reason=user_err.message,
                        )
                        return Result.fail(translate_identity_error(user_err))
                    await self.uow.user_repo.delete(user)

            await self.uow.commit()

        bound_logger.info("delete_tenant.completed")
        return Result.ok(None)
