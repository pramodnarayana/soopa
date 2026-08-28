from database.uow import BaseSqlAlchemyUnitOfWork
from identity.adapters.outbound.database.api_token_repository import PostgresApiTokenRepository
from identity.adapters.outbound.database.role_repository import PostgresRoleRepository
from identity.adapters.outbound.database.user_repository import PostgresUserRepository
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ucp.adapters.outbound.database.idempotency_repository import SqlAlchemyIdempotencyRepository
from ucp.adapters.outbound.database.postgres_app_repository import PostgresAppRepository
from ucp.adapters.outbound.database.tenant_repository import TenantRepository
from ucp.adapters.outbound.database.webhook_repository import SqlAlchemyWebhookRepository
from ucp.ports.outbound.uow_port import UcpUnitOfWorkPort


class SqlAlchemyUcpUnitOfWork(BaseSqlAlchemyUnitOfWork, UcpUnitOfWorkPort):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self.tenant_repo = TenantRepository(session=self.session)
        self.user_repo = PostgresUserRepository(session=self.session)
        self.api_token_repo = PostgresApiTokenRepository(session=self.session)
        self.app_repo = PostgresAppRepository(session=self.session)
        self.role_repo = PostgresRoleRepository(session=self.session)
        self.webhook_repo = SqlAlchemyWebhookRepository(session=self.session)
        self.idempotency_repo = SqlAlchemyIdempotencyRepository(session=self.session)

    async def _pre_commit(self) -> None:
        await self.session.execute(text("NOTIFY ucp_outbox_wakeup;"))
        await self.session.execute(text("NOTIFY identity_outbox_wakeup;"))
