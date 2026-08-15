from typing import Any, Self

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ucp.adapters.outbound.database.postgres_api_token_repository import PostgresApiTokenRepository
from ucp.adapters.outbound.database.postgres_app_repository import PostgresAppRepository
from ucp.adapters.outbound.database.role_repository import PostgresRoleRepository
from ucp.adapters.outbound.database.tenant_repository import TenantRepository
from ucp.adapters.outbound.database.user_repository import UserRepository
from ucp.adapters.outbound.database.webhook_repository import SqlAlchemyWebhookRepository
from ucp.ports.uow import UcpUnitOfWorkPort


class SqlAlchemyUcpUnitOfWork(UcpUnitOfWorkPort):
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.tenant_repo = TenantRepository(session=self.session)
        self.user_repo = UserRepository(session=self.session)
        self.api_token_repo = PostgresApiTokenRepository(session=self.session)
        self.app_repo = PostgresAppRepository(session=self.session)
        self.role_repo = PostgresRoleRepository(session=self.session)
        self.webhook_repo = SqlAlchemyWebhookRepository(session=self.session)

    async def __aenter__(self) -> Self:
        if not self.session.in_transaction():
            await self.session.begin()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if exc_type is not None:
            await self.rollback()
        # Note: We do NOT auto-commit on success here.
        # True UnitOfWork requires explicit .commit() call in the UseCase.

    async def commit(self) -> None:
        await self.session.execute(text("NOTIFY ucp_outbox_wakeup;"))
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()
