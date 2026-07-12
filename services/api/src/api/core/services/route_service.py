import logging
from typing import Any
from uuid import UUID

from api.domain.models import (
    CreateInboundRouteCmd,
    CreateOutboundRouteCmd,
    RouteEntity,
    UpdateInboundRouteCmd,
    UpdateOutboundRouteCmd,
)
from api.ports.repository import ControlPlaneRepositoryPort
from domain.events import ProvisioningEventType

logger = logging.getLogger(__name__)


class RouteService:
    """
    Domain service responsible for the lifecycle of Inbound and Outbound EDI Routes,
    including resolution of partner names for list operations.
    """

    def __init__(self, global_repo: ControlPlaneRepositoryPort) -> None:
        self.global_repo = global_repo

    async def create_inbound_route(self, tenant_id: int, cmd: CreateInboundRouteCmd) -> RouteEntity:
        logger.info(f"Creating Inbound Route for sender {cmd.isa_sender_id} in tenant {tenant_id}")
        route_id = await self.global_repo.create_inbound_route(tenant_id=tenant_id, cmd=cmd)
        await self.global_repo.create_outbox_event(
            tenant_id=tenant_id,
            event_type=ProvisioningEventType.INBOUND_ROUTE_CREATED,
            payload={"route_id": str(route_id), "tenant_id": tenant_id},
        )
        return RouteEntity(route_id=route_id, tenant_id=tenant_id, direction="INBOUND")

    async def update_inbound_route(
        self, tenant_id: int, route_id: UUID, cmd: UpdateInboundRouteCmd
    ) -> bool:
        res = await self.global_repo.update_inbound_route(tenant_id, route_id, cmd)
        if res:
            await self.global_repo.create_outbox_event(
                tenant_id=tenant_id,
                event_type=ProvisioningEventType.INBOUND_ROUTE_UPDATED,
                payload={"route_id": str(route_id), "tenant_id": tenant_id},
            )
        return res

    async def delete_inbound_route(self, tenant_id: int, route_id: UUID) -> bool:
        res = await self.global_repo.delete_inbound_route(tenant_id, route_id)
        if res:
            await self.global_repo.create_outbox_event(
                tenant_id=tenant_id,
                event_type=ProvisioningEventType.INBOUND_ROUTE_DELETED,
                payload={"route_id": str(route_id), "tenant_id": tenant_id},
            )
        return res

    async def create_outbound_route(
        self, tenant_id: int, cmd: CreateOutboundRouteCmd
    ) -> RouteEntity:
        logger.info(f"Creating Outbound Route for sender {cmd.isa_sender_id} in tenant {tenant_id}")
        route_id = await self.global_repo.create_outbound_route(tenant_id=tenant_id, cmd=cmd)
        await self.global_repo.create_outbox_event(
            tenant_id=tenant_id,
            event_type=ProvisioningEventType.OUTBOUND_ROUTE_CREATED,
            payload={"route_id": str(route_id), "tenant_id": tenant_id},
        )
        return RouteEntity(route_id=route_id, tenant_id=tenant_id, direction="OUTBOUND")

    async def update_outbound_route(
        self, tenant_id: int, route_id: UUID, cmd: UpdateOutboundRouteCmd
    ) -> bool:
        res = await self.global_repo.update_outbound_route(tenant_id, route_id, cmd)
        if res:
            await self.global_repo.create_outbox_event(
                tenant_id=tenant_id,
                event_type=ProvisioningEventType.OUTBOUND_ROUTE_UPDATED,
                payload={"route_id": str(route_id), "tenant_id": tenant_id},
            )
        return res

    async def delete_outbound_route(self, tenant_id: int, route_id: UUID) -> bool:
        res = await self.global_repo.delete_outbound_route(tenant_id, route_id)
        if res:
            await self.global_repo.create_outbox_event(
                tenant_id=tenant_id,
                event_type=ProvisioningEventType.OUTBOUND_ROUTE_DELETED,
                payload={"route_id": str(route_id), "tenant_id": tenant_id},
            )
        return res

    async def list_routes(self, tenant_id: int) -> list[dict[str, Any]]:
        routes_data = await self.global_repo.get_all_routes(tenant_id)
        inbound = routes_data.get("inbound", [])
        outbound = routes_data.get("outbound", [])

        as2_ids: set[UUID] = set()
        sftp_ids: set[UUID] = set()
        webhook_ids: set[UUID] = set()

        for r in inbound:
            if r.as2_partner_id:
                as2_ids.add(r.as2_partner_id)
            if r.sftp_partner_id:
                sftp_ids.add(r.sftp_partner_id)
            if r.webhook_id:
                webhook_ids.add(r.webhook_id)

        for r in outbound:
            if r.as2_partner_id:
                as2_ids.add(r.as2_partner_id)
            if r.sftp_partner_id:
                sftp_ids.add(r.sftp_partner_id)

        as2_names = (
            await self.global_repo.get_as2_partners_by_ids(tenant_id, list(as2_ids))
            if as2_ids
            else {}
        )
        sftp_names = (
            await self.global_repo.get_sftp_partners_by_ids(tenant_id, list(sftp_ids))
            if sftp_ids
            else {}
        )
        webhook_names = (
            await self.global_repo.get_webhooks_by_ids(tenant_id, list(webhook_ids))
            if webhook_ids
            else {}
        )

        results: list[dict[str, Any]] = []

        def _resolve_destination(r: Any) -> tuple[str, str]:
            if r.as2_partner_id:
                return "AS2", as2_names.get(r.as2_partner_id, str(r.as2_partner_id))
            if r.sftp_partner_id:
                return "SFTP", sftp_names.get(r.sftp_partner_id, str(r.sftp_partner_id))
            if getattr(r, "webhook_id", None):
                return "WEBHOOK", webhook_names.get(r.webhook_id, str(r.webhook_id))
            return "UNKNOWN", "Unknown"

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
                    "webhook_id": r.webhook_id,
                    "as2_partner_id": r.as2_partner_id,
                    "sftp_partner_id": r.sftp_partner_id,
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
                    "isa_sender_id": r.isa_sender_id,
                    "isa_sender_qualifier": r.isa_sender_qualifier,
                    "isa_receiver_id": r.isa_receiver_id,
                    "isa_receiver_qualifier": r.isa_receiver_qualifier,
                    "gs_sender_id": r.gs_sender_id,
                    "gs_receiver_id": r.gs_receiver_id,
                    "default_standard": r.default_standard,
                    "default_version": r.default_version,
                    "transaction_type": r.transaction_type,
                    "destination_type": dest_type,
                    "destination_name": dest_name,
                    "as2_partner_id": r.as2_partner_id,
                    "sftp_partner_id": r.sftp_partner_id,
                    "active": r.active,
                }
            )

        return results
