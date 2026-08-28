import structlog

from edi.application.dto import UpdateInboundRouteCmd
from edi.domain.events import EdiEventType, ProvisioningEvent
from edi.ports.outbound.uow import ControlPlaneUnitOfWorkPort as ControlPlaneUnitOfWork

logger = structlog.get_logger(__name__)


class UpdateInboundRouteUseCase:
    def __init__(self, uow: ControlPlaneUnitOfWork) -> None:
        self.uow = uow

    async def update_inbound_route(
        self,
        tenant_id: str,
        route_id: str,
        cmd: UpdateInboundRouteCmd,
        idempotency_key: str | None = None,
    ) -> bool:
        res = await self.uow.inbound_routes.update_inbound_route(tenant_id, route_id, cmd)
        if res:
            await self.uow.control_plane_outbox.publish_outbox_event(
                ProvisioningEvent(
                    tenant_id=tenant_id,
                    event_type=EdiEventType.edi_inbound_route_updated,
                    resource_id=str(route_id),
                ),
                idempotency_key=idempotency_key,
            )
        return res
