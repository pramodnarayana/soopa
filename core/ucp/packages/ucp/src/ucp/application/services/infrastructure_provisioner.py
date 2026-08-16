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
            logger.error("Cannot provision infrastructure: missing tenant_id/event_id in event")
            return

        try:
            async with self.uow_factory() as uow, uow:
                app_id_from_event = event.payload.get("app_id")
                if not app_id_from_event:
                    logger.error("No app_id in payload for event {event_id}", event_id=event_id)
                    return

                    # Look up the App ID strictly
                    app = await uow.app_repo.find_by_id(app_id_from_event)
                    if not app:
                        logger.error(
                            "Cannot subscribe tenant {tenant_id} to unknown app id '{app_id_from_event}'",
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
                        "Successfully provisioned infrastructure for tenant {tenant_id} (App: {app_id_from_event}, Shard: {shard_id})",
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
            logger.error("Cannot process unsubscription: missing tenant_id/event_id in event")
            return

        try:
            async with self.uow_factory() as uow, uow:
                app_id_from_event = event.payload.get("app_id")
                if not app_id_from_event:
                    logger.error("No app_id in payload for event {event_id}", event_id=event_id)
                    return

                    # Look up the App ID strictly
                    app = await uow.app_repo.find_by_id(app_id_from_event)
                    if not app:
                        logger.error(
                            "Cannot unsubscribe tenant {tenant_id} from unknown app id '{app_id_from_event}'",
                            tenant_id=tenant_id,
                            app_id_from_event=app_id_from_event,
                        )
                        return

                    # Upsert the AppSubscription to 'inactive'
                    await uow.tenant_repo.upsert_app_subscription(tenant_id, app.id, "inactive")

                    await uow.commit()
                    logger.info(
                        "Successfully deactivated subscription for tenant {tenant_id} (App: {app_id_from_event})",
                        tenant_id=tenant_id,
                        app_id_from_event=app_id_from_event,
                    )

        except Exception:
            logger.exception("app.unsubscribed_failed", event_id=event_id)
