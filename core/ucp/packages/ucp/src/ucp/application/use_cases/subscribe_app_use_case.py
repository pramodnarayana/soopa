import structlog
from pydantic import BaseModel

from ucp.application.use_cases._tenant_helpers import resolve_tenant_or_raise
from ucp.ports.outbound.uow_port import UcpUnitOfWorkPort

logger = structlog.get_logger(__name__)


class SubscribeAppCommand(BaseModel):
    tenant_id: str
    app_id: str


class SubscribeAppUseCase:
    def __init__(self, uow: UcpUnitOfWorkPort):
        self.uow = uow

    async def execute(
        self, command: SubscribeAppCommand, idempotency_key: str | None = None
    ) -> None:
        async with self.uow as uow:
            tenant = await resolve_tenant_or_raise(uow, command.tenant_id)

            tenant.subscribe(command.app_id)

            await uow.tenant_repo.save(tenant, idempotency_key)
            await uow.commit()

        logger.info(
            "tenant_subscribed_to_app",
            tenant_id=tenant.id,
            app_id=command.app_id,
        )
