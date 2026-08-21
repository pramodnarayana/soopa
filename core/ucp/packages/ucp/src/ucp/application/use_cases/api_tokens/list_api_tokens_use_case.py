from ucp.domain.models.api_token import ApiTokenDomainModel
from ucp.ports.outbound.uow_port import UcpUnitOfWorkPort


class ListApiTokensUseCase:
    def __init__(self, uow: UcpUnitOfWorkPort):
        self.uow = uow

    async def execute(self, tenant_id: str) -> list[ApiTokenDomainModel]:
        async with self.uow:
            return await self.uow.api_token_repo.get_all_by_tenant(tenant_id)
