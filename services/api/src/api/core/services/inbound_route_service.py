import logging
from uuid import UUID

from api.core.uow import UnitOfWork
from api.domain.models import (
    CreateInboundRouteCmd,
    RouteEntity,
    UpdateInboundRouteCmd,
)
from domain.events import ProvisioningEventType

logger = logging.getLogger(__name__)


class InboundRouteService:
    def __init__(self, uow: UnitOfWork) -> None:
        self.uow = uow

    async def create_inbound_route(self, tenant_id: int, cmd: CreateInboundRouteCmd) -> RouteEntity:
        logger.info(f"Creating Inbound Route for sender {cmd.isa_sender_id} in tenant {tenant_id}")
        route_id = await self.uow.control_plane.create_inbound_route(tenant_id=tenant_id, cmd=cmd)
        await self.uow.control_plane.publish_outbox_event(
            tenant_id=tenant_id,
            event_type=ProvisioningEventType.INBOUND_ROUTE_CREATED,
            payload={"route_id": str(route_id), "tenant_id": tenant_id},
        )
        return RouteEntity(route_id=route_id, tenant_id=tenant_id, direction="INBOUND")

    async def update_inbound_route(
        self, tenant_id: int, route_id: UUID, cmd: UpdateInboundRouteCmd
    ) -> bool:
        res = await self.uow.control_plane.update_inbound_route(tenant_id, route_id, cmd)
        if res:
            await self.uow.control_plane.publish_outbox_event(
                tenant_id=tenant_id,
                event_type=ProvisioningEventType.INBOUND_ROUTE_UPDATED,
                payload={"route_id": str(route_id), "tenant_id": tenant_id},
            )
        return res

    async def delete_inbound_route(self, tenant_id: int, route_id: UUID) -> bool:
        res = await self.uow.control_plane.delete_inbound_route(tenant_id, route_id)
        if res:
            await self.uow.control_plane.publish_outbox_event(
                tenant_id=tenant_id,
                event_type=ProvisioningEventType.INBOUND_ROUTE_DELETED,
                payload={"route_id": str(route_id), "tenant_id": tenant_id},
            )
        return res
