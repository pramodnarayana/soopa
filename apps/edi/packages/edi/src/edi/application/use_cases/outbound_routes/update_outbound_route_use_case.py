import dataclasses

import structlog

from edi.application.dto import UNSET, UpdateOutboundRouteCmd
from edi.domain.events import EdiEventType, ProvisioningEvent
from edi.domain.models.outbound_routes import OutboundRouteDomainModel
from edi.ports.outbound.uow import ControlPlaneUnitOfWorkPort as ControlPlaneUnitOfWork

logger = structlog.get_logger(__name__)


class UpdateOutboundRouteUseCase:
    def __init__(self, uow: ControlPlaneUnitOfWork) -> None:
        self.uow = uow

    async def execute(
        self,
        tenant_id: str,
        route_id: str,
        cmd: UpdateOutboundRouteCmd,
        idempotency_key: str | None = None,
    ) -> bool:
        aggregate = await self.uow.outbound_routes.get_outbound_route(tenant_id, route_id)
        if not aggregate:
            return False

        persisted_fields = {field.name for field in dataclasses.fields(OutboundRouteDomainModel)}
        for field in dataclasses.fields(cmd):
            value = getattr(cmd, field.name)
            if value is not UNSET:
                if field.name not in persisted_fields:
                    raise ValueError(f"Unsupported outbound route field: {field.name}")
                setattr(aggregate, field.name, value)

        aggregate.add_domain_event(
            ProvisioningEvent(
                tenant_id=tenant_id,
                event_type=EdiEventType.edi_outbound_route_updated,
                resource_id=route_id,
                explicit_idempotency_key=idempotency_key,
            )
        )

        await self.uow.outbound_routes.save(aggregate)
        return True
