from datetime import UTC, datetime

import structlog

from edi.application.dto import CreateInboundRouteCmd
from edi.domain.events import EdiEventType, ProvisioningEvent
from edi.domain.models.base import ProcessingMode
from edi.domain.models.inbound_routes import InboundRouteDomainModel
from edi.ports.outbound.uow import ControlPlaneUnitOfWorkPort as ControlPlaneUnitOfWork

logger = structlog.get_logger(__name__)


class CreateInboundRouteUseCase:
    def __init__(self, uow: ControlPlaneUnitOfWork) -> None:
        self.uow = uow

    async def create_inbound_route(
        self, tenant_id: str, cmd: CreateInboundRouteCmd, idempotency_key: str | None = None
    ) -> InboundRouteDomainModel:
        logger.info(
            "Creating Inbound Route for sender {cmd_isa_sender_id} in tenant {tenant_id}",
            cmd_isa_sender_id=cmd.isa_sender_id,
            tenant_id=tenant_id,
        )
        route_id = InboundRouteDomainModel.new_id()

        aggregate = InboundRouteDomainModel(
            id=route_id,
            tenant_id=tenant_id,
            name=cmd.name,
            isa_sender_id=cmd.isa_sender_id,
            isa_receiver_id=cmd.isa_receiver_id,
            active=False,
            created_at=datetime.now(UTC).replace(tzinfo=None),
            updated_at=datetime.now(UTC).replace(tzinfo=None),
            trading_partner_id=cmd.trading_partner_id,
            gs_sender_id=cmd.gs_sender_id,
            gs_receiver_id=cmd.gs_receiver_id,
            transaction_type=cmd.transaction_type,
            webhook_id=str(cmd.webhook_id) if cmd.webhook_id else None,
            as2_partner_id=str(cmd.as2_partner_id) if cmd.as2_partner_id else None,
            sftp_partner_id=str(cmd.sftp_partner_id) if cmd.sftp_partner_id else None,
            processing_mode=ProcessingMode(cmd.processing_mode) if cmd.processing_mode else None,
        )

        aggregate.add_domain_event(
            ProvisioningEvent(
                tenant_id=tenant_id,
                event_type=EdiEventType.edi_inbound_route_created,
                resource_id=route_id,
                explicit_idempotency_key=idempotency_key,
            )
        )

        await self.uow.inbound_routes.save(aggregate)

        logger.info(
            "inbound_route_created",
            route_id=route_id,
            tenant_id=tenant_id,
        )
        return aggregate
