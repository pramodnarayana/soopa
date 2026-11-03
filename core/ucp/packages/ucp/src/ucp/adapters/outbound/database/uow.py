from database.uow import BaseSqlAlchemyUnitOfWork
from identity.ports.outbound.api_token_repository_port import ApiTokenRepositoryPort
from identity.ports.outbound.role_repository_port import RoleRepositoryPort
from identity.ports.outbound.user_repository_port import UserRepositoryPort
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ucp.ports.outbound.app_repository_port import AppRepositoryPort
from ucp.ports.outbound.idempotency_repository_port import IdempotencyRepositoryPort
from ucp.ports.outbound.tenant_repository_port import TenantRepositoryPort
from ucp.ports.outbound.uow_port import UcpUnitOfWorkPort
from ucp.ports.outbound.webhook_repository_port import WebhookRepositoryPort


class SqlAlchemyUcpUnitOfWork(BaseSqlAlchemyUnitOfWork, UcpUnitOfWorkPort):
    def __init__(
        self,
        session: AsyncSession,
        *,
        tenant_repo: TenantRepositoryPort,
        user_repo: UserRepositoryPort,
        api_token_repo: ApiTokenRepositoryPort,
        app_repo: AppRepositoryPort,
        role_repo: RoleRepositoryPort,
        webhook_repo: WebhookRepositoryPort,
        idempotency_repo: IdempotencyRepositoryPort,
    ) -> None:
        super().__init__(session)
        self.tenant_repo = tenant_repo
        self.user_repo = user_repo
        self.api_token_repo = api_token_repo
        self.app_repo = app_repo
        self.role_repo = role_repo
        self.webhook_repo = webhook_repo
        self.idempotency_repo = idempotency_repo

    async def _pre_commit(self) -> None:
        await self.session.execute(text("NOTIFY ucp_outbox_wakeup;"))
        await self.session.execute(text("NOTIFY identity_outbox_wakeup;"))
