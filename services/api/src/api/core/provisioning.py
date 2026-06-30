import logging
from typing import Any

from api.domain.models import (
    CreateAS2PartnershipCmd,
    CreateAS2TradingPartnerCmd,
    CreateInboundRouteCmd,
    CreateOutboundRouteCmd,
    CreateSFTPPartnerCmd,
    CreateWebhookPartnerCmd,
    PartnerEntity,
    RouteEntity,
)
from api.ports.repository import ControlPlaneRepositoryPort, DataPlaneRepositoryPort

logger = logging.getLogger(__name__)


class ProvisioningService:
    """
    Core application service for orchestrating the Provisioning of Trading Partners.
    Decoupled from FastAPI, SQLAlchemy, and AWS.
    """

    def __init__(
        self,
        tenant_repo: DataPlaneRepositoryPort,
        global_repo: ControlPlaneRepositoryPort | None = None,
    ) -> None:
        self.tenant_repo = tenant_repo
        self.global_repo = global_repo

    async def create_as2_partner(
        self, tenant_id: int, cmd: CreateAS2TradingPartnerCmd
    ) -> PartnerEntity:
        if not self.global_repo:
            raise ValueError("Control plane repository is required for AS2 partner creation")

        logger.info(f"Provisioning AS2 partner {cmd.name} for tenant {tenant_id}")

        # 1. Create in Global DB
        partner_id = await self.global_repo.create_as2_identity(tenant_id=tenant_id, cmd=cmd)

        # 2. Emit Outbox Event (Worker will provision certificates/vault if needed)
        payload = {
            "partner_id": str(partner_id),
            "tenant_id": tenant_id,
        }
        await self.global_repo.create_outbox_event(
            tenant_id=tenant_id,
            event_type="AS2_PARTNER_CREATED",
            payload=payload,
        )

        return PartnerEntity(
            partner_id=partner_id,
            tenant_id=tenant_id,
            type="AS2",
            status="PROVISIONING",
        )

    async def create_sftp_partner(self, tenant_id: int, cmd: CreateSFTPPartnerCmd) -> PartnerEntity:
        logger.info(f"Creating SFTP partner {cmd.name} for tenant {tenant_id}")

        # Written directly to Tenant DB
        partner_id = await self.tenant_repo.create_sftp_partner(cmd=cmd)

        return PartnerEntity(
            partner_id=partner_id,
            tenant_id=tenant_id,
            type="SFTP",
            status="ACTIVE",
        )

    async def create_as2_partnership(
        self, tenant_id: int, cmd: CreateAS2PartnershipCmd
    ) -> PartnerEntity:
        if not self.global_repo:
            raise ValueError("Control plane repository is required for AS2 partnership creation")

        logger.info(
            f"Provisioning AS2 partnership {cmd.local_partner_id} -> {cmd.remote_partner_id}"
        )
        partner_id = await self.global_repo.create_as2_partnership(tenant_id=tenant_id, cmd=cmd)

        return PartnerEntity(
            partner_id=partner_id,
            tenant_id=tenant_id,
            type="AS2_PARTNERSHIP",
            status="ACTIVE",
        )

    async def create_webhook_partner(
        self, tenant_id: int, cmd: CreateWebhookPartnerCmd
    ) -> PartnerEntity:
        logger.info(f"Creating Webhook partner {cmd.name} for tenant {tenant_id}")

        # Written directly to Tenant DB
        partner_id = await self.tenant_repo.create_webhook_partner(cmd=cmd)

        return PartnerEntity(
            partner_id=partner_id,
            tenant_id=tenant_id,
            type="WEBHOOK",
            status="ACTIVE",
        )

    async def create_inbound_route(self, tenant_id: int, cmd: CreateInboundRouteCmd) -> RouteEntity:
        logger.info(f"Creating Inbound Route for sender {cmd.isa_sender_id} in tenant {tenant_id}")
        route_id = await self.tenant_repo.create_inbound_route(cmd=cmd)

        return RouteEntity(
            route_id=route_id,
            tenant_id=tenant_id,
            direction="INBOUND",
        )

    async def create_outbound_route(
        self, tenant_id: int, cmd: CreateOutboundRouteCmd
    ) -> RouteEntity:
        logger.info(f"Creating Outbound Route for sender {cmd.isa_sender_id} in tenant {tenant_id}")
        route_id = await self.tenant_repo.create_outbound_route(cmd=cmd)

        return RouteEntity(
            route_id=route_id,
            tenant_id=tenant_id,
            direction="OUTBOUND",
        )

    async def list_routes(self, tenant_id: int) -> list[dict[str, Any]]:
        routes_data = await self.tenant_repo.get_all_routes()
        inbound = routes_data.get("inbound", [])
        outbound = routes_data.get("outbound", [])

        # Collect IDs to fetch names
        as2_ids = set()
        sftp_ids = set()
        webhook_ids = set()

        for r in inbound:
            if r.as2_partner_id:
                as2_ids.add(r.as2_partner_id)
            if r.sftp_partner_id:
                sftp_ids.add(r.sftp_partner_id)
            if r.webhook_partner_id:
                webhook_ids.add(r.webhook_partner_id)

        for r in outbound:
            # Note: outbound routes map to as2_partner_id
            if r.as2_partner_id:
                as2_ids.add(r.as2_partner_id)
            if r.sftp_partner_id:
                sftp_ids.add(r.sftp_partner_id)

        # Fetch names
        as2_names = (
            await self.global_repo.get_as2_partners_by_ids(list(as2_ids), tenant_id)
            if self.global_repo
            else {}
        )
        sftp_names = await self.tenant_repo.get_sftp_partners_by_ids(list(sftp_ids))
        webhook_names = await self.tenant_repo.get_webhook_partners_by_ids(list(webhook_ids))

        results = []
        for r in inbound:
            dest_type = "UNKNOWN"
            dest_name = "Unknown"
            if r.as2_partner_id:
                dest_type = "AS2"
                dest_name = as2_names.get(r.as2_partner_id, str(r.as2_partner_id))
            elif r.sftp_partner_id:
                dest_type = "SFTP"
                dest_name = sftp_names.get(r.sftp_partner_id, str(r.sftp_partner_id))
            elif r.webhook_partner_id:
                dest_type = "WEBHOOK"
                dest_name = webhook_names.get(r.webhook_partner_id, str(r.webhook_partner_id))

            results.append(
                {
                    "route_id": r.id,
                    "direction": "INBOUND",
                    "isa_sender_id": r.isa_sender_id,
                    "isa_receiver_id": r.isa_receiver_id,
                    "destination_type": dest_type,
                    "destination_name": dest_name,
                }
            )

        for r in outbound:
            dest_type = "UNKNOWN"
            dest_name = "Unknown"
            if r.as2_partner_id:
                dest_type = "AS2"
                dest_name = as2_names.get(r.as2_partner_id, str(r.as2_partner_id))
            elif r.sftp_partner_id:
                dest_type = "SFTP"
                dest_name = sftp_names.get(r.sftp_partner_id, str(r.sftp_partner_id))

            results.append(
                {
                    "route_id": r.id,
                    "direction": "OUTBOUND",
                    "isa_sender_id": r.isa_sender_id,
                    "isa_receiver_id": r.isa_receiver_id,
                    "destination_type": dest_type,
                    "destination_name": dest_name,
                }
            )

        return results
