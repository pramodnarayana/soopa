import structlog
from domain.events import EdiEventType, ProvisioningEvent
from domain.models import ConnectionType, Direction, InboundRouteDomainModel

from edi.domain.models import (
    CreateInboundRouteCmd,
    InboundRouteListEntity,
    RouteEntity,
    UpdateInboundRouteCmd,
)
from edi.ports.uow import ControlPlaneUnitOfWorkPort as ControlPlaneUnitOfWork

logger = structlog.get_logger(__name__)


class InboundRouteService:
    """
    Domain service responsible for the lifecycle of Inbound EDI Routes,
    including resolution of partner names for list operations.
    """

    def __init__(self, uow: ControlPlaneUnitOfWork) -> None:
        self.uow = uow

    async def create_inbound_route(
        self, tenant_id: str, cmd: CreateInboundRouteCmd, idempotency_key: str | None = None
    ) -> RouteEntity:
        logger.info(
            "Creating Inbound Route for sender {cmd.isa_sender_id} in tenant {tenant_id}",
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
        return RouteEntity(route_id=route_id, tenant_id=tenant_id, direction=Direction.INBOUND)

    async def update_inbound_route(
        self,
        tenant_id: str,
        route_id: str,
        cmd: UpdateInboundRouteCmd,
        idempotency_key: str | None = None,
    ) -> bool:
        res = await self.uow.inbound_routes.update_inbound_route(tenant_id, route_id, cmd)
        if res:
            await self.uow.control_plane_outbox.publish_outbox_event(
                ProvisioningEvent(
                    tenant_id=tenant_id,
                    event_type=EdiEventType.edi_inbound_route_updated,
                    resource_id=str(route_id),
                ),
                idempotency_key=idempotency_key,
            )
        return res

    async def delete_inbound_route(
        self, tenant_id: str, route_id: str, idempotency_key: str | None = None
    ) -> bool:
        res = await self.uow.inbound_routes.delete_inbound_route(tenant_id, route_id)
        if res:
            await self.uow.control_plane_outbox.publish_outbox_event(
                ProvisioningEvent(
                    tenant_id=tenant_id,
                    event_type=EdiEventType.edi_inbound_route_deleted,
                    resource_id=str(route_id),
                ),
                idempotency_key=idempotency_key,
            )
        return res

    async def list_inbound_routes(self, tenant_id: str) -> list[InboundRouteListEntity]:
        inbound = await self.uow.inbound_routes.list_inbound_routes(tenant_id)

        as2_ids: set[str] = set()
        sftp_ids: set[str] = set()
        webhook_ids: set[str] = set()

        for r in inbound:
            if r.as2_partner_id:
                as2_ids.add(r.as2_partner_id)
            if r.sftp_partner_id:
                sftp_ids.add(r.sftp_partner_id)
            if r.webhook_id:
                webhook_ids.add(r.webhook_id)

        as2_names = (
            await self.uow.as2_partners.get_as2_partners_by_ids(tenant_id, list(as2_ids))
            if as2_ids
            else {}
        )
        sftp_names = (
            await self.uow.sftp_partners.get_sftp_partners_by_ids(tenant_id, list(sftp_ids))
            if sftp_ids
            else {}
        )
        webhook_names = (
            await self.uow.webhooks.get_webhooks_by_ids(tenant_id, list(webhook_ids))
            if webhook_ids
            else {}
        )

        results: list[InboundRouteListEntity] = []

        def _resolve_destination(r: InboundRouteDomainModel) -> tuple[ConnectionType | str, str]:
            if r.as2_partner_id:
                return ConnectionType.AS2, as2_names.get(r.as2_partner_id, str(r.as2_partner_id))
            if r.sftp_partner_id:
                return ConnectionType.SFTP, sftp_names.get(
                    r.sftp_partner_id, str(r.sftp_partner_id)
                )
            if r.webhook_id:
                return ConnectionType.WEBHOOK, webhook_names.get(r.webhook_id, str(r.webhook_id))
            return "UNKNOWN", "Unknown"

        for r in inbound:
            dest_type, dest_name = _resolve_destination(r)

            results.append(
                InboundRouteListEntity(
                    route_id=r.id,
                    name=r.name,
                    direction=Direction.INBOUND,
                    trading_partner_id=r.trading_partner_id,
                    isa_sender_id=r.isa_sender_id,
                    isa_receiver_id=r.isa_receiver_id,
                    gs_sender_id=r.gs_sender_id,
                    gs_receiver_id=r.gs_receiver_id,
                    transaction_type=r.transaction_type,
                    destination_type=dest_type,
                    destination_name=dest_name,
                    webhook_id=str(r.webhook_id) if r.webhook_id else None,
                    as2_partner_id=r.as2_partner_id,
                    sftp_partner_id=r.sftp_partner_id,
                    active=r.active,
                )
            )

        return results
