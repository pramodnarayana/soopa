from __future__ import annotations

import structlog
from identity.domain.api_token import ApiToken

from ucp.ports.outbound.uow_port import UcpUnitOfWorkPort

logger = structlog.get_logger(__name__)


class ListApiTokensUseCase:
    def __init__(self, uow: UcpUnitOfWorkPort) -> None:
        self.uow = uow

    async def execute(self, tenant_id: str) -> list[ApiToken]:
        logger.debug("api_token_list.started", tenant_id=tenant_id)
        async with self.uow:
            tokens = await self.uow.api_token_repo.get_all_by_tenant(tenant_id)
        logger.debug("api_token_list.completed", tenant_id=tenant_id, count=len(tokens))
        return tokens
