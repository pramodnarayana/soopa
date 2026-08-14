import structlog
from pydantic import BaseModel

from ucp.core.exceptions import ResourceNotFoundError
from ucp.ports.uow import UcpUnitOfWorkPort

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
            tenant = await uow.tenant_repo.find_by_id(command.tenant_id)
            if not tenant:
                tenant = await uow.tenant_repo.find_by_idp_tenant_id(command.tenant_id)
                if not tenant:
                    raise ResourceNotFoundError("Tenant not found")

            tenant.subscribe(command.app_id)

            await uow.tenant_repo.save(tenant, idempotency_key)
            await uow.commit()

        logger.info(
            "tenant_subscribed_to_app",
            tenant_id=tenant.id,
            app_id=command.app_id,
        )
