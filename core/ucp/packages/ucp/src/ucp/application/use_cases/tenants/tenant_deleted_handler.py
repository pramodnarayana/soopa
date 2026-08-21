from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

import structlog

from ucp.ports.outbound.uow import UcpUnitOfWorkPort

logger = structlog.get_logger(__name__)


class TenantDeletedEventHandler:
    """
    Handles TenantDeletedEvent asynchronously to perform cascading soft deletes
    for all tenant-owned infrastructure and identity resources.
    """

    def __init__(self, uow_factory: Callable[[], AbstractAsyncContextManager[UcpUnitOfWorkPort]]):
        self.uow_factory = uow_factory

    async def handle(self, tenant_id: str) -> None:
        """
        Soft deletes infrastructure (Webhooks, Roles, ApiTokens, and ApiKeys) for the given tenant.
        """
        bound_logger = logger.bind(tenant_id=tenant_id)
        bound_logger.info("tenant_deleted_handler.started")

        try:
            async with self.uow_factory() as uow, uow:
                await uow.tenant_repo.soft_delete_tenant_infrastructure(tenant_id)
                await uow.commit()

            bound_logger.info("tenant_deleted_handler.completed")
        except Exception:
            bound_logger.exception("tenant_deleted_handler.failed")
            raise
