import structlog

from edi.application.dto import CreateInboundRouteCmd
from edi.domain.events import EdiEventType, ProvisioningEvent
from edi.domain.models import InboundRouteDomainModel
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
        route_id = await self.uow.inbound_routes.create_inbound_route(tenant_id=tenant_id, cmd=cmd)
        await self.uow.control_plane_outbox.publish_outbox_event(
            ProvisioningEvent(
                tenant_id=tenant_id,
                event_type=EdiEventType.edi_inbound_route_created,
                resource_id=str(route_id),
            ),
            idempotency_key=idempotency_key,
        )

        route_obj = await self.uow.inbound_routes.get_inbound_route_by_id(tenant_id, str(route_id))
        if not route_obj:
            raise ValueError("Inbound route not found after creation")
        return InboundRouteDomainModel(
            id=route_obj.id,
            tenant_id=tenant_id,
            name=route_obj.name,
            isa_sender_id=route_obj.isa_sender_id,
            isa_receiver_id=route_obj.isa_receiver_id,
            active=route_obj.active,
            created_at=route_obj.created_at,
            updated_at=route_obj.updated_at,
            trading_partner_id=route_obj.trading_partner_id,
            gs_sender_id=route_obj.gs_sender_id,
            gs_receiver_id=route_obj.gs_receiver_id,
            transaction_type=route_obj.transaction_type,
            webhook_id=str(route_obj.webhook_id) if route_obj.webhook_id else None,
            as2_partner_id=str(route_obj.as2_partner_id) if route_obj.as2_partner_id else None,
            sftp_partner_id=str(route_obj.sftp_partner_id) if route_obj.sftp_partner_id else None,
        )
