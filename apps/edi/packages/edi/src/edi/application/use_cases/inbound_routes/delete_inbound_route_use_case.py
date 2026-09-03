import structlog

from edi.domain.enums import EdiEventType
from edi.domain.events import ProvisioningEvent
from edi.ports.outbound.uow import ControlPlaneUnitOfWorkPort as ControlPlaneUnitOfWork

logger = structlog.get_logger(__name__)


class DeleteInboundRouteUseCase:
    def __init__(self, uow: ControlPlaneUnitOfWork) -> None:
        self.uow = uow

    async def delete_inbound_route(
        self, tenant_id: str, route_id: str, idempotency_key: str | None = None
    ) -> bool:
        aggregate = await self.uow.inbound_routes.get_inbound_route_by_id(tenant_id, route_id)
        if not aggregate:
            return False

        aggregate.add_domain_event(
            ProvisioningEvent(
                tenant_id=tenant_id,
                event_type=EdiEventType.edi_inbound_route_deleted,
                resource_id=route_id,
                explicit_idempotency_key=idempotency_key,
            )
        )
        await self.uow.inbound_routes.delete(aggregate)
        return True
