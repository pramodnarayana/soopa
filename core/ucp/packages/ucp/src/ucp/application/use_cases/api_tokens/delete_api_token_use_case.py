from __future__ import annotations

import structlog
from seedwork.domain.exceptions import Result

from ucp.application.use_cases.api_key_authenticator import invalidate_api_key_cache
from ucp.domain.exceptions import TokenNotFoundUcpError, UcpError
from ucp.ports.outbound.uow_port import UcpUnitOfWorkPort

logger = structlog.get_logger(__name__)


class DeleteApiTokenUseCase:
    def __init__(self, uow: UcpUnitOfWorkPort) -> None:
        self.uow = uow

    async def execute(self, token_id: str, tenant_id: str) -> Result[None, UcpError]:
        bound_logger = logger.bind(tenant_id=tenant_id, token_id=token_id)
        bound_logger.info("api_token_delete.started")

        async with self.uow:
            existing = await self.uow.api_token_repo.get_by_id(token_id, tenant_id)
            deleted = await self.uow.api_token_repo.delete(token_id, tenant_id)
            if not deleted:
                bound_logger.error("api_token_delete.not_found")
                return Result.fail(TokenNotFoundUcpError.for_id(token_id))
            await self.uow.commit()

        if existing is not None:
            invalidate_api_key_cache(existing.client_id)

        bound_logger.info("api_token_delete.completed")
        return Result.ok(None)
