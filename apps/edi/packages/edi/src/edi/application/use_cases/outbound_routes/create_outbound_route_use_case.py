import structlog

from edi.application.dto import CreateOutboundRouteCmd
from edi.domain.models import OutboundRouteDomainModel
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
        route_id = await self.uow.outbound_routes.create_outbound_route(
            tenant_id=tenant_id, cmd=cmd
        )
        #         await self.uow.control_plane_outbox.publish_outbox_event(
        #             ProvisioningEvent(
        #                 tenant_id=tenant_id,
        #                 event_type=EdiEventType.edi_outbound_route_created,
        #                 resource_id=str(route_id),
        #             ),
        #             idempotency_key=idempotency_key,
        #         )

        route_obj = await self.uow.outbound_routes.get_outbound_route(tenant_id, str(route_id))
        if not route_obj:
            raise ValueError("Outbound route not found after creation")
        return OutboundRouteDomainModel(
            id=route_obj.id,
            tenant_id=tenant_id,
            trading_partner_id=route_obj.trading_partner_id,
            name=route_obj.name,
            active=route_obj.active,
            created_at=route_obj.created_at,
            updated_at=route_obj.updated_at,
            as2_partner_id=str(route_obj.as2_partner_id) if route_obj.as2_partner_id else None,
            sftp_partner_id=str(route_obj.sftp_partner_id) if route_obj.sftp_partner_id else None,
        )
