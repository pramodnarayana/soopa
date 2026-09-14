from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from seedwork.constants import SystemIdPrefix
from seedwork.utils import generate_id

from edi.domain.enums import EdiConnectionType, EdiEventType
from edi.domain.events import ProvisioningEvent
from edi.domain.models.outbound_routes import OutboundRouteDomainModel
from edi.ports.outbound.uow import ControlPlaneUnitOfWorkPort as ControlPlaneUnitOfWork

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class CreateOutboundRouteCmd:
    isa_sender_id: str
    isa_receiver_id: str
    transaction_type: str
    as2_partner_id: str | None = None
    sftp_partner_id: str | None = None
    name: str | None = None
    connection_type: EdiConnectionType | None = None
    trading_partner_id: str | None = None


class CreateOutboundRouteUseCase:
    def __init__(self, uow: ControlPlaneUnitOfWork) -> None:
        self.uow = uow

    async def execute(
        self, tenant_id: str, cmd: CreateOutboundRouteCmd, idempotency_key: str | None = None
    ) -> OutboundRouteDomainModel:
        logger.info(
            "creating_outbound_route",
            trading_partner_id=cmd.trading_partner_id,
            tenant_id=tenant_id,
        )
        route_id = OutboundRouteDomainModel.new_id()

        aggregate = OutboundRouteDomainModel(
            id=route_id,
            tenant_id=tenant_id,
            trading_partner_id=cmd.trading_partner_id,
            name=cmd.name,
            active=False,
            created_at=datetime.now(UTC).replace(tzinfo=None),
            updated_at=datetime.now(UTC).replace(tzinfo=None),
            as2_partner_id=str(cmd.as2_partner_id) if cmd.as2_partner_id else None,
            sftp_partner_id=str(cmd.sftp_partner_id) if cmd.sftp_partner_id else None,
            connection_type=cmd.connection_type,
        )

        aggregate.add_domain_event(
            ProvisioningEvent(
                tenant_id=tenant_id,
                event_type=EdiEventType.edi_outbound_route_created,
                resource_id=route_id,
                idempotency_key=idempotency_key or generate_id(SystemIdPrefix.GENERIC),
            )
        )

        await self.uow.outbound_routes.save(aggregate)

        logger.info(
            "outbound_route_created",
            route_id=route_id,
            tenant_id=tenant_id,
        )
        return aggregate
