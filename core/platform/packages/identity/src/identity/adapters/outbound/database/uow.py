from database.uow import BaseSqlAlchemyUnitOfWork
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from identity.adapters.outbound.database.api_token_repository import PostgresApiTokenRepository
from identity.adapters.outbound.database.role_repository import PostgresRoleRepository
from identity.adapters.outbound.database.user_repository import PostgresUserRepository
from identity.ports.outbound.uow_port import IdentityUnitOfWorkPort


class SqlAlchemyIdentityUnitOfWork(BaseSqlAlchemyUnitOfWork, IdentityUnitOfWorkPort):
    """
    Concrete Unit of Work adapter for the Identity context.
    """

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self.user_repo = PostgresUserRepository(session=self.session)
        self.role_repo = PostgresRoleRepository(session=self.session)
        self.api_token_repo = PostgresApiTokenRepository(session=self.session)

    async def _pre_commit(self) -> None:

        # Wake up the outbox relay
        await self.session.execute(text("NOTIFY identity_outbox_wakeup;"))
