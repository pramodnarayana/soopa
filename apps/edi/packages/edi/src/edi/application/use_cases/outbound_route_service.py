import structlog

from edi.application.dto import (
    CreateOutboundRouteCmd,
    UpdateOutboundRouteCmd,
)
from edi.domain.events import EdiEventType, ProvisioningEvent
from edi.domain.models import (
    ConnectionType,
    OutboundRouteDomainModel,
)
from edi.ports.outbound.uow import ControlPlaneUnitOfWorkPort as ControlPlaneUnitOfWork

logger = structlog.get_logger(__name__)


class OutboundRouteService:
    """
    Domain service responsible for the lifecycle of Outbound EDI Routes,
    including resolution of partner names for list operations.
    """

    def __init__(self, uow: ControlPlaneUnitOfWork) -> None:
        self.uow = uow

    async def create_outbound_route(
        self, tenant_id: str, cmd: CreateOutboundRouteCmd, idempotency_key: str | None = None
    ) -> OutboundRouteDomainModel:
        logger.info(
            "Creating Outbound Route for partner {cmd.trading_partner_id} in tenant {tenant_id}",
            cmd_trading_partner_id=cmd.trading_partner_id,
            tenant_id=tenant_id,
        )
        route_id = await self.uow.outbound_routes.create_outbound_route(
            tenant_id=tenant_id, cmd=cmd
        )
        await self.uow.control_plane_outbox.publish_outbox_event(
            ProvisioningEvent(
                tenant_id=tenant_id,
                event_type=EdiEventType.edi_outbound_route_created,
                resource_id=str(route_id),
            ),
            idempotency_key=idempotency_key,
        )

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

    async def update_outbound_route(
        self,
        tenant_id: str,
        route_id: str,
        cmd: UpdateOutboundRouteCmd,
        idempotency_key: str | None = None,
    ) -> bool:
        res = await self.uow.outbound_routes.update_outbound_route(tenant_id, route_id, cmd)
        if res:
            await self.uow.control_plane_outbox.publish_outbox_event(
                ProvisioningEvent(
                    tenant_id=tenant_id,
                    event_type=EdiEventType.edi_outbound_route_updated,
                    resource_id=str(route_id),
                ),
                idempotency_key=idempotency_key,
            )
        return res

    async def delete_outbound_route(
        self, tenant_id: str, route_id: str, idempotency_key: str | None = None
    ) -> bool:
        res = await self.uow.outbound_routes.delete_outbound_route(tenant_id, route_id)
        if res:
            await self.uow.control_plane_outbox.publish_outbox_event(
                ProvisioningEvent(
                    tenant_id=tenant_id,
                    event_type=EdiEventType.edi_outbound_route_deleted,
                    resource_id=str(route_id),
                ),
                idempotency_key=idempotency_key,
            )
        return res

    async def list_outbound_routes(self, tenant_id: str) -> list[OutboundRouteDomainModel]:
        outbound = await self.uow.outbound_routes.list_outbound_routes(tenant_id)

        as2_ids: set[str] = set()
        sftp_ids: set[str] = set()

        for out_r in outbound:
            if out_r.as2_partner_id:
                as2_ids.add(out_r.as2_partner_id)
            if out_r.sftp_partner_id:
                sftp_ids.add(out_r.sftp_partner_id)

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

        results: list[OutboundRouteDomainModel] = []

        def _resolve_destination(r: OutboundRouteDomainModel) -> tuple[ConnectionType | str, str]:
            if r.as2_partner_id:
                return ConnectionType.AS2, as2_names.get(r.as2_partner_id, str(r.as2_partner_id))
            if r.sftp_partner_id:
                return ConnectionType.SFTP, sftp_names.get(
                    r.sftp_partner_id, str(r.sftp_partner_id)
                )
            return "UNKNOWN", "Unknown"

        for out_r in outbound:
            _dest_type, _dest_name = _resolve_destination(out_r)

            results.append(
                OutboundRouteDomainModel(
                    id=out_r.id,
                    tenant_id=tenant_id,
                    trading_partner_id=out_r.trading_partner_id,
                    name=out_r.name,
                    active=out_r.active,
                    created_at=out_r.created_at,
                    updated_at=out_r.updated_at,
                    as2_partner_id=str(out_r.as2_partner_id) if out_r.as2_partner_id else None,
                    sftp_partner_id=str(out_r.sftp_partner_id) if out_r.sftp_partner_id else None,
                    direction="OUTBOUND",
                    destination_name=_dest_name,
                )
            )

        return results
