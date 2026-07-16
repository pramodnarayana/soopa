import logging
from typing import Any
from uuid import UUID

from api.core.uow import UnitOfWork
from api.domain.models import (
    CreateOutboundRouteCmd,
    OutboundRouteListEntity,
    RouteEntity,
    UpdateOutboundRouteCmd,
)
from domain.events import ProvisioningEventType
from domain.models import ConnectionType, Direction

logger = logging.getLogger(__name__)


class OutboundRouteService:
    """
    Domain service responsible for the lifecycle of Outbound EDI Routes,
    including resolution of partner names for list operations.
    """

    def __init__(self, uow: UnitOfWork) -> None:
        self.uow = uow

    async def create_outbound_route(
        self, tenant_id: int, cmd: CreateOutboundRouteCmd
    ) -> RouteEntity:
        logger.info(
            f"Creating Outbound Route for partner {cmd.trading_partner_id} in tenant {tenant_id}"
        )
        route_id = await self.uow.outbound_routes.create_outbound_route(
            tenant_id=tenant_id, cmd=cmd
        )
        await self.uow.outbox.publish_outbox_event(
            tenant_id=tenant_id,
            event_type=ProvisioningEventType.OUTBOUND_ROUTE_CREATED,
            payload={"route_id": str(route_id), "tenant_id": tenant_id},
        )
        return RouteEntity(route_id=route_id, tenant_id=tenant_id, direction=Direction.OUTBOUND)

    async def update_outbound_route(
        self, tenant_id: int, route_id: UUID, cmd: UpdateOutboundRouteCmd
    ) -> bool:
        res = await self.uow.outbound_routes.update_outbound_route(tenant_id, route_id, cmd)
        if res:
            await self.uow.outbox.publish_outbox_event(
                tenant_id=tenant_id,
                event_type=ProvisioningEventType.OUTBOUND_ROUTE_UPDATED,
                payload={"route_id": str(route_id), "tenant_id": tenant_id},
            )
        return res

    async def delete_outbound_route(self, tenant_id: int, route_id: UUID) -> bool:
        res = await self.uow.outbound_routes.delete_outbound_route(tenant_id, route_id)
        if res:
            await self.uow.outbox.publish_outbox_event(
                tenant_id=tenant_id,
                event_type=ProvisioningEventType.OUTBOUND_ROUTE_DELETED,
                payload={"route_id": str(route_id), "tenant_id": tenant_id},
            )
        return res

    async def list_outbound_routes(self, tenant_id: int) -> list[OutboundRouteListEntity]:
        from domain.models import OutboundRouteDomainModel

        routes_dict = await self.uow.outbound_routes.get_all_routes(tenant_id)
        outbound: list[OutboundRouteDomainModel] = routes_dict.get("outbound", [])  # type: ignore

        as2_ids: set[UUID] = set()
        sftp_ids: set[UUID] = set()

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

        results: list[OutboundRouteListEntity] = []

        def _resolve_destination(r: Any) -> tuple[ConnectionType | str, str]:
            if r.as2_partner_id:
                return ConnectionType.AS2, as2_names.get(r.as2_partner_id, str(r.as2_partner_id))
            if r.sftp_partner_id:
                return ConnectionType.SFTP, sftp_names.get(
                    r.sftp_partner_id, str(r.sftp_partner_id)
                )
            return "UNKNOWN", "Unknown"

        for out_r in outbound:
            dest_type, dest_name = _resolve_destination(out_r)

            results.append(
                OutboundRouteListEntity(
                    route_id=out_r.id,
                    name=out_r.name,
                    direction=Direction.OUTBOUND,
                    trading_partner_id=out_r.trading_partner_id,
                    transaction_type="*",
                    isa_sender_id=None,
                    isa_receiver_id=None,
                    destination_type=dest_type,
                    destination_name=dest_name,
                    webhook_id=None,
                    as2_partner_id=out_r.as2_partner_id,
                    sftp_partner_id=out_r.sftp_partner_id,
                    active=out_r.active,
                )
            )

        return results
