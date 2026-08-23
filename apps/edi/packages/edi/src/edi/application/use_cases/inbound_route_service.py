import structlog

from edi.application.dto import (
    CreateInboundRouteCmd,
    UpdateInboundRouteCmd,
)
from edi.domain.events import EdiEventType, ProvisioningEvent
from edi.domain.models import (
    ConnectionType,
    InboundRouteDomainModel,
)
from edi.ports.outbound.uow import ControlPlaneUnitOfWorkPort as ControlPlaneUnitOfWork

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
    ) -> InboundRouteDomainModel:
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

    async def list_inbound_routes(self, tenant_id: str) -> list[InboundRouteDomainModel]:
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
        webhook_names: dict[str, str] = {}

        results: list[InboundRouteDomainModel] = []

        def _resolve_destination(r: InboundRouteDomainModel) -> tuple[ConnectionType | str, str]:
            if r.as2_partner_id:
                return ConnectionType.AS2, as2_names.get(r.as2_partner_id, str(r.as2_partner_id))
            if r.sftp_partner_id:
                return ConnectionType.SFTP, sftp_names.get(
                    r.sftp_partner_id, str(r.sftp_partner_id)
                )
            if r.webhook_id:
                # Use a persisted route display name (r.name) as fallback, then ID
                display_name = webhook_names.get(r.webhook_id) or r.name or str(r.webhook_id)
                return ConnectionType.WEBHOOK, display_name
            return "UNKNOWN", "Unknown"

        for r in inbound:
            _dest_type, _dest_name = _resolve_destination(r)

            results.append(
                InboundRouteDomainModel(
                    id=r.id,
                    tenant_id=tenant_id,
                    name=r.name,
                    isa_sender_id=r.isa_sender_id,
                    isa_receiver_id=r.isa_receiver_id,
                    active=r.active,
                    created_at=r.created_at,
                    updated_at=r.updated_at,
                    trading_partner_id=r.trading_partner_id,
                    gs_sender_id=r.gs_sender_id,
                    gs_receiver_id=r.gs_receiver_id,
                    transaction_type=r.transaction_type,
                    webhook_id=str(r.webhook_id) if r.webhook_id else None,
                    as2_partner_id=str(r.as2_partner_id) if r.as2_partner_id else None,
                    sftp_partner_id=str(r.sftp_partner_id) if r.sftp_partner_id else None,
                    direction="INBOUND",
                    destination_name=_dest_name,
                )
            )

        return results
