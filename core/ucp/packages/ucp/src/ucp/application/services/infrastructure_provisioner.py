from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

import structlog

from ucp.ports.ucp_event_listener import UcpEventMessage
from ucp.ports.uow import UcpUnitOfWorkPort

logger = structlog.get_logger(__name__)


class InfrastructureProvisioner:
    """
    Subscribes to UCP domain events and provisions the requisite platform infrastructure.
    (e.g., allocating a database shard to a tenant, mapping the app subscription in the control plane).

    The uow_factory returns an async context manager that provides a UcpUnitOfWorkPort.
    Event handlers use double-context entry (`async with factory() as uow, uow:`) to ensure:
    1. The factory-provided context (session lifecycle) is entered first
    2. The yielded unit of work (transaction lifecycle) is entered second
    This preserves correct exit order: transaction rollback/close happens before session disposal.
    """

    def __init__(self, uow_factory: Callable[[], AbstractAsyncContextManager[UcpUnitOfWorkPort]]):
        self.uow_factory = uow_factory

    async def handle_app_subscribed(self, event: UcpEventMessage) -> None:
        """
        Handles the 'app.subscribed' event (2-hop provisioning).
        """
        tenant_id = event.tenant_id
        event_id = event.id
        if not tenant_id or not event_id:
            logger.error("app_subscribed_missing_ids", tenant_id=tenant_id, event_id=event_id)
            return

        try:
            async with self.uow_factory() as uow, uow:
                app_id_from_event = event.payload.get("app_id")
                if not app_id_from_event:
                    logger.error("app_subscribed_missing_app_id", event_id=event_id)
                    return

                # Look up the App ID strictly
                app = await uow.app_repo.find_by_id(app_id_from_event)
                if not app:
                    logger.error(
                        "app_subscribed_unknown_app_id",
                        tenant_id=tenant_id,
                        app_id_from_event=app_id_from_event,
                    )
                    return

                # Upsert the AppSubscription to 'active'
                await uow.tenant_repo.upsert_app_subscription(tenant_id, app.id, "active")

                # Allocate Database Shard (Hardcoded to edi_shard_1 for now)
                shard_id = "edi_shard_1"
                await uow.tenant_repo.allocate_shard(tenant_id, app.id, shard_id)

                await uow.commit()
                logger.info(
                    "app_subscribed_infrastructure_provisioned",
                    tenant_id=tenant_id,
                    app_id_from_event=app_id_from_event,
                    shard_id=shard_id,
                )

        except Exception:
            logger.exception("app.subscribed_failed", event_id=event_id)

    async def handle_app_unsubscribed(self, event: UcpEventMessage) -> None:
        """
        Handles the 'app.unsubscribed' event by setting the subscription status to 'inactive'.
        """
        tenant_id = event.tenant_id
        event_id = event.id
        if not tenant_id or not event_id:
            logger.error("app_unsubscribed_missing_ids", tenant_id=tenant_id, event_id=event_id)
            return

        try:
            async with self.uow_factory() as uow, uow:
                app_id_from_event = event.payload.get("app_id")
                if not app_id_from_event:
                    logger.error("app_unsubscribed_missing_app_id", event_id=event_id)
                    return

                # Look up the App ID strictly
                app = await uow.app_repo.find_by_id(app_id_from_event)
                if not app:
                    logger.error(
                        "app_unsubscribed_unknown_app_id",
                        tenant_id=tenant_id,
                        app_id_from_event=app_id_from_event,
                    )
                    return

                # Upsert the AppSubscription to 'inactive'
                await uow.tenant_repo.upsert_app_subscription(tenant_id, app.id, "inactive")

                await uow.commit()
                logger.info(
                    "app_unsubscribed_deactivated",
                    tenant_id=tenant_id,
                    app_id_from_event=app_id_from_event,
                )

        except Exception:
            logger.exception("app.unsubscribed_failed", event_id=event_id)
