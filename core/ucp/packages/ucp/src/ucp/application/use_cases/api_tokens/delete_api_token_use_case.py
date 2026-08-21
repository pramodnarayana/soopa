from ucp.ports.outbound.uow_port import UcpUnitOfWorkPort


class DeleteApiTokenUseCase:
    def __init__(self, uow: UcpUnitOfWorkPort):
        self.uow = uow

    async def execute(self, token_id: str, tenant_id: str) -> bool:
        async with self.uow:
            deleted = await self.uow.api_token_repo.delete(token_id, tenant_id)
            await self.uow.commit()
            return deleted
