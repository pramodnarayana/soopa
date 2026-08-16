import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from ucp_models.events import ControlPlaneOutbox
from ucp_models.infrastructure import ShardRegistry
from ucp_models.subscriptions import App, AppSubscription

from ucp.ports.ucp_event_listener import UcpEventMessage

logger = structlog.get_logger(__name__)


class InfrastructureProvisioner:
    """
    Subscribes to UCP domain events and provisions the requisite platform infrastructure.
    (e.g., allocating a database shard to a tenant, mapping the app subscription in the control plane).
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self.session_factory = session_factory

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
            async with self.session_factory() as session:
                # 1. Fetch the actual domain event payload from outbox
                stmt = select(ControlPlaneOutbox.payload).where(ControlPlaneOutbox.id == event_id)
                payload = await session.scalar(stmt)
                if not payload:
                    logger.error("Could not find outbox event {event_id}", event_id=event_id)
                    return

                app_id_from_event = payload.get("app_id")
                if not app_id_from_event:
                    logger.error("No app_id in payload for event {event_id}", event_id=event_id)
                    return

                # 2. Look up the App ID strictly
                app_stmt = select(App.id).where(App.id == app_id_from_event)
                app_id = await session.scalar(app_stmt)
                if not app_id:
                    logger.error(
                        "Cannot subscribe tenant {tenant_id} to unknown app id '{app_id_from_event}'",
                        tenant_id=tenant_id,
                        app_id_from_event=app_id_from_event,
                    )
                    return

                # 3. Upsert the AppSubscription to 'active'
                sub_stmt = select(AppSubscription).where(
                    AppSubscription.tenant_id == tenant_id, AppSubscription.app_id == app_id
                )
                existing_sub = await session.scalar(sub_stmt)
                if not existing_sub:
                    new_sub = AppSubscription(
                        tenant_id=tenant_id, app_id=app_id, tier="standard", status="active"
                    )
                    session.add(new_sub)
                else:
                    existing_sub.status = "active"

                # 4. Allocate Database Shard (Hardcoded to edi_shard_1 for now)
                shard_id = "edi_shard_1"
                shard_stmt = select(ShardRegistry).where(
                    ShardRegistry.tenant_id == tenant_id, ShardRegistry.app_id == app_id
                )
                existing_shard = await session.scalar(shard_stmt)

                if not existing_shard:
                    new_shard = ShardRegistry(tenant_id=tenant_id, app_id=app_id, shard_id=shard_id)
                    session.add(new_shard)
                else:
                    existing_shard.shard_id = shard_id

                await session.commit()
                logger.info(
                    "Successfully provisioned infrastructure for tenant {tenant_id} (App: {app_id_from_event}, Shard: {shard_id})",
                    tenant_id=tenant_id,
                    app_id_from_event=app_id_from_event,
                    shard_id=shard_id,
                )

        except Exception:
            logger.exception(
                "Failed to process app.subscribed for event {event_id}", event_id=event_id
            )

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
            async with self.session_factory() as session:
                # 1. Fetch the actual domain event payload from outbox
                stmt = select(ControlPlaneOutbox.payload).where(ControlPlaneOutbox.id == event_id)
                payload = await session.scalar(stmt)
                if not payload:
                    logger.error("Could not find outbox event {event_id}", event_id=event_id)
                    return

                app_id_from_event = payload.get("app_id")
                if not app_id_from_event:
                    logger.error("No app_id in payload for event {event_id}", event_id=event_id)
                    return

                # 2. Look up the App ID strictly
                app_stmt = select(App.id).where(App.id == app_id_from_event)
                app_id = await session.scalar(app_stmt)
                if not app_id:
                    logger.error(
                        "Cannot unsubscribe tenant {tenant_id} from unknown app id '{app_id_from_event}'",
                        tenant_id=tenant_id,
                        app_id_from_event=app_id_from_event,
                    )
                    return

                # 3. Set the AppSubscription to 'inactive'
                sub_stmt = select(AppSubscription).where(
                    AppSubscription.tenant_id == tenant_id, AppSubscription.app_id == app_id
                )
                existing_sub = await session.scalar(sub_stmt)
                if existing_sub:
                    existing_sub.status = "inactive"
                    await session.commit()
                    logger.info(
                        "Successfully deactivated subscription for tenant {tenant_id} (App: {app_id_from_event})",
                        tenant_id=tenant_id,
                        app_id_from_event=app_id_from_event,
                    )
                else:
                    logger.warning(
                        "Attempted to deactivate non-existent subscription for tenant {tenant_id} (App: {app_id_from_event})",
                        tenant_id=tenant_id,
                        app_id_from_event=app_id_from_event,
                    )

        except Exception:
            logger.exception(
                "Failed to process app.unsubscribed for event {event_id}", event_id=event_id
            )
