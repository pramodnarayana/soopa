import logging
from typing import Any
from uuid import UUID

from api.core.uow import UnitOfWork
from api.domain.models import (
    CreateOutboundRouteCmd,
    RouteEntity,
    UpdateOutboundRouteCmd,
)
from domain.events import ProvisioningEventType

logger = logging.getLogger(__name__)


class OutboundRouteService:
    def __init__(self, uow: UnitOfWork) -> None:
        self.uow = uow

    async def create_outbound_route(
        self, tenant_id: int, cmd: CreateOutboundRouteCmd
    ) -> RouteEntity:
        logger.info(
            f"Creating Outbound Route for partner {cmd.as2_partner_id} in tenant {tenant_id}"
        )
        route_id = await self.uow.outbound_routes.create_outbound_route(
            tenant_id=tenant_id, cmd=cmd
        )
        await self.uow.outbox.publish_outbox_event(
            tenant_id=tenant_id,
            event_type=ProvisioningEventType.OUTBOUND_ROUTE_CREATED,
            payload={"route_id": str(route_id), "tenant_id": tenant_id},
        )
        return RouteEntity(route_id=route_id, tenant_id=tenant_id, direction="OUTBOUND")

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

    async def get_all_routes(self, tenant_id: int) -> dict[str, list[Any]]:
        return await self.uow.outbound_routes.get_all_routes(tenant_id)

    async def list_routes(self, tenant_id: int) -> list[dict[str, Any]]:
        """
        Returns a unified list of inbound and outbound routes enriched with
        partner/destination names. Batch-fetches names to avoid N+1 queries.
        """
        routes_data = await self.uow.outbound_routes.get_all_routes(tenant_id)
        inbound: list[Any] = routes_data.get("inbound", [])
        outbound: list[Any] = routes_data.get("outbound", [])

        as2_ids: set[UUID] = set()
        sftp_ids: set[UUID] = set()
        webhook_ids: set[UUID] = set()

        for r in inbound:
            if getattr(r, "as2_partner_id", None):
                as2_ids.add(r.as2_partner_id)
            if getattr(r, "sftp_partner_id", None):
                sftp_ids.add(r.sftp_partner_id)
            if getattr(r, "webhook_id", None):
                webhook_ids.add(r.webhook_id)

        for r in outbound:
            if getattr(r, "as2_partner_id", None):
                as2_ids.add(r.as2_partner_id)
            if getattr(r, "sftp_partner_id", None):
                sftp_ids.add(r.sftp_partner_id)

        as2_names: dict[UUID, str] = (
            await self.uow.as2_partnerships.get_as2_partners_by_ids(tenant_id, list(as2_ids))
            if as2_ids
            else {}
        )
        sftp_names: dict[UUID, str] = (
            await self.uow.sftp_partners.get_sftp_partners_by_ids(tenant_id, list(sftp_ids))
            if sftp_ids
            else {}
        )
        webhook_names: dict[UUID, str] = (
            await self.uow.webhooks.get_webhooks_by_ids(tenant_id, list(webhook_ids))
            if webhook_ids
            else {}
        )

        def _resolve_destination(r: Any) -> tuple[str, str]:
            if getattr(r, "as2_partner_id", None):
                return "AS2", as2_names.get(r.as2_partner_id, str(r.as2_partner_id))
            if getattr(r, "sftp_partner_id", None):
                return "SFTP", sftp_names.get(r.sftp_partner_id, str(r.sftp_partner_id))
            if getattr(r, "webhook_id", None):
                return "WEBHOOK", webhook_names.get(r.webhook_id, str(r.webhook_id))
            return "UNKNOWN", "Unknown"

        results: list[dict[str, Any]] = []

        for r in inbound:
            dest_type, dest_name = _resolve_destination(r)
            results.append(
                {
                    "route_id": r.id,
                    "name": r.name,
                    "direction": "INBOUND",
                    "trading_partner_id": r.trading_partner_id,
                    "isa_sender_id": r.isa_sender_id,
                    "isa_receiver_id": r.isa_receiver_id,
                    "gs_sender_id": r.gs_sender_id,
                    "gs_receiver_id": r.gs_receiver_id,
                    "transaction_type": r.transaction_type,
                    "destination_type": dest_type,
                    "destination_name": dest_name,
                    "webhook_id": getattr(r, "webhook_id", None),
                    "as2_partner_id": getattr(r, "as2_partner_id", None),
                    "sftp_partner_id": getattr(r, "sftp_partner_id", None),
                    "active": r.active,
                }
            )

        for r in outbound:
            dest_type, dest_name = _resolve_destination(r)
            results.append(
                {
                    "route_id": r.id,
                    "name": r.name,
                    "direction": "OUTBOUND",
                    "trading_partner_id": r.trading_partner_id,
                    "transaction_type": "*",
                    "isa_sender_id": None,
                    "isa_receiver_id": None,
                    "gs_sender_id": None,
                    "gs_receiver_id": None,
                    "destination_type": dest_type,
                    "destination_name": dest_name,
                    "webhook_id": None,
                    "as2_partner_id": getattr(r, "as2_partner_id", None),
                    "sftp_partner_id": getattr(r, "sftp_partner_id", None),
                    "active": r.active,
                }
            )

        return results

    async def get_trading_partner_name(self, route: Any) -> str | None:
        if getattr(route, "as2_partner_id", None):
            partners = await self.uow.as2_partners.list_as2_partners(tenant_id=0)
            for p in partners:
                if p.id == route.as2_partner_id:
                    return p.name  # type: ignore
        elif getattr(route, "sftp_partner_id", None):
            sftp = await self.uow.sftp_partners.list_sftp_partners(tenant_id=0)
            for p in sftp:
                if p.id == route.sftp_partner_id:
                    return p.name  # type: ignore
        elif getattr(route, "webhook_id", None):
            webhooks = await self.uow.webhooks.list_webhooks(tenant_id=0)
            for p in webhooks:
                if p.id == route.webhook_id:
                    return p.name  # type: ignore
        return None
