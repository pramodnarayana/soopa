import dataclasses
from datetime import UTC, datetime

import structlog
from seedwork.domain.types import UNSET

from edi.application.dtos.commands import UpdateInboundRouteCmd
from edi.domain.events import EdiEventType, ProvisioningEvent
from edi.domain.models.inbound_routes import InboundRouteDomainModel
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
        aggregate = await self.uow.inbound_routes.get_inbound_route_by_id(tenant_id, route_id)
        if not aggregate:
            return False

        persisted_fields = {field.name for field in dataclasses.fields(InboundRouteDomainModel)}
        for field in dataclasses.fields(cmd):
            value = getattr(cmd, field.name)
            if value is not UNSET:
                if field.name not in persisted_fields:
                    raise ValueError(f"Unsupported inbound route field: {field.name}")
                setattr(aggregate, field.name, value)
        aggregate.updated_at = datetime.now(UTC).replace(tzinfo=None)

        aggregate.add_domain_event(
            ProvisioningEvent(
                tenant_id=tenant_id,
                event_type=EdiEventType.edi_inbound_route_updated,
                resource_id=route_id,
                explicit_idempotency_key=idempotency_key,
            )
        )

        await self.uow.inbound_routes.save(aggregate)
        return True
