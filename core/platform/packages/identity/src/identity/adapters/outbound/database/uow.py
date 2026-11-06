from database.uow import BaseSqlAlchemyUnitOfWork
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from identity.ports.outbound.api_token_repository_port import ApiTokenRepositoryPort
from identity.ports.outbound.capability_repository_port import CapabilityRepositoryPort
from identity.ports.outbound.role_repository_port import RoleRepositoryPort
from identity.ports.outbound.uow_port import IdentityUnitOfWorkPort
from identity.ports.outbound.user_repository_port import UserRepositoryPort


class SqlAlchemyIdentityUnitOfWork(BaseSqlAlchemyUnitOfWork, IdentityUnitOfWorkPort):
    """
    Concrete Unit of Work adapter for the Identity context.
    """

    def __init__(
        self,
        session: AsyncSession,
        *,
        user_repo: UserRepositoryPort,
        role_repo: RoleRepositoryPort,
        api_token_repo: ApiTokenRepositoryPort,
        capability_repo: CapabilityRepositoryPort,
    ) -> None:
        super().__init__(session)
        self.user_repo = user_repo
        self.role_repo = role_repo
        self.api_token_repo = api_token_repo
        self.capability_repo = capability_repo

    async def _pre_commit(self) -> None:
        # Wake up the outbox relay
        await self.session.execute(text("NOTIFY identity_outbox_wakeup;"))
