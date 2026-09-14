from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from seedwork.constants import SystemIdPrefix
from seedwork.domain.types import UNSET, UnsetType
from seedwork.utils import generate_id

from edi.domain.enums import EdiConnectionType, EdiEventType
from edi.domain.events import ProvisioningEvent
from edi.ports.outbound.uow import ControlPlaneUnitOfWorkPort as ControlPlaneUnitOfWork

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class UpdateOutboundRouteCmd:
    as2_partner_id: str | UnsetType | None = UNSET
    sftp_partner_id: str | UnsetType | None = UNSET
    active: bool | UnsetType = UNSET
    name: str | UnsetType | None = UNSET
    connection_type: EdiConnectionType | UnsetType | None = UNSET
    trading_partner_id: str | UnsetType | None = UNSET


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

        if not isinstance(cmd.as2_partner_id, UnsetType):
            aggregate.as2_partner_id = cmd.as2_partner_id
        if not isinstance(cmd.sftp_partner_id, UnsetType):
            aggregate.sftp_partner_id = cmd.sftp_partner_id
        if not isinstance(cmd.active, UnsetType):
            aggregate.active = cmd.active
        if not isinstance(cmd.name, UnsetType):
            aggregate.name = cmd.name
        if not isinstance(cmd.connection_type, UnsetType):
            aggregate.connection_type = cmd.connection_type
        if not isinstance(cmd.trading_partner_id, UnsetType):
            aggregate.trading_partner_id = cmd.trading_partner_id

        aggregate.updated_at = datetime.now(UTC)

        aggregate.add_domain_event(
            ProvisioningEvent(
                tenant_id=tenant_id,
                event_type=EdiEventType.edi_outbound_route_updated,
                resource_id=route_id,
                idempotency_key=idempotency_key or generate_id(SystemIdPrefix.GENERIC),
            )
        )

        await self.uow.outbound_routes.save(aggregate)

        logger.info(
            "outbound_route_updated",
            route_id=route_id,
            tenant_id=tenant_id,
        )

        return True
