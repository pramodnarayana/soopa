from identity.domain.models.api_token import ApiTokenDomainModel
from identity.domain.models.api_token_models import UpdateApiTokenCommand

from ucp.ports.outbound.uow_port import UcpUnitOfWorkPort


class UpdateApiTokenUseCase:
    def __init__(self, uow: UcpUnitOfWorkPort):
        self.uow = uow

    async def execute(
        self, token_id: str, tenant_id: str, command: UpdateApiTokenCommand
    ) -> ApiTokenDomainModel | None:
        async with self.uow:
            token = await self.uow.api_token_repo.update(
                token_id,
                tenant_id,
                name=command.name,
                active=command.active,
            )
            await self.uow.commit()
            return token
