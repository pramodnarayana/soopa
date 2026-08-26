import structlog

from edi.ports.outbound.uow import ControlPlaneUnitOfWorkPort as ControlPlaneUnitOfWork

logger = structlog.get_logger(__name__)


class DeleteOutboundRouteUseCase:
    def __init__(self, uow: ControlPlaneUnitOfWork) -> None:
        self.uow = uow

    async def execute(
        self, tenant_id: str, route_id: str, idempotency_key: str | None = None
    ) -> bool:
        res = await self.uow.outbound_routes.delete_outbound_route(tenant_id, route_id)
        if res:
            pass
        #             await self.uow.control_plane_outbox.publish_outbox_event(
        #                 ProvisioningEvent(
        #                     tenant_id=tenant_id,
        #                     event_type=EdiEventType.edi_outbound_route_deleted,
        #                     resource_id=str(route_id),
        #                 ),
        #                 idempotency_key=idempotency_key,
        #             )
        return res
