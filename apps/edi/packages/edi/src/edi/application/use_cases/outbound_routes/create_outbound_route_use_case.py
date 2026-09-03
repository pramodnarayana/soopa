from datetime import UTC, datetime

import structlog

from edi.application.dtos.commands import CreateOutboundRouteCmd
from edi.domain.enums import EdiEventType
from edi.domain.events import ProvisioningEvent
from edi.domain.models.outbound_routes import OutboundRouteDomainModel
from edi.ports.outbound.uow import ControlPlaneUnitOfWorkPort as ControlPlaneUnitOfWork

logger = structlog.get_logger(__name__)


class CreateOutboundRouteUseCase:
    def __init__(self, uow: ControlPlaneUnitOfWork) -> None:
        self.uow = uow

    async def execute(
        self, tenant_id: str, cmd: CreateOutboundRouteCmd, idempotency_key: str | None = None
    ) -> OutboundRouteDomainModel:
        logger.info(
            "Creating Outbound Route for partner {cmd_trading_partner_id} in tenant {tenant_id}",
            cmd_trading_partner_id=cmd.trading_partner_id,
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
        )

        aggregate.add_domain_event(
            ProvisioningEvent(
                tenant_id=tenant_id,
                event_type=EdiEventType.edi_outbound_route_created,
                resource_id=route_id,
                explicit_idempotency_key=idempotency_key,
            )
        )

        await self.uow.outbound_routes.save(aggregate)

        logger.info(
            "outbound_route_created",
            route_id=route_id,
            tenant_id=tenant_id,
        )
        return aggregate
