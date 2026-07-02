import logging
from typing import Any
from uuid import UUID

from api.domain.models import (
    CreateAS2PartnershipCmd,
    CreateAS2TradingPartnerCmd,
    CreateInboundRouteCmd,
    CreateOutboundRouteCmd,
    CreateSFTPPartnerCmd,
    CreateWebhookPartnerCmd,
    PartnerEntity,
    RouteEntity,
    UpdateAS2PartnershipCmd,
    UpdateAS2TradingPartnerCmd,
    UpdateSFTPPartnerCmd,
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

    async def delete_as2_partner(self, tenant_id: int, partner_id: UUID) -> None:
        if not self.global_repo:
            raise ValueError("Control plane repository is required for AS2 partner deletion")
        logger.info(f"Deleting AS2 partner {partner_id} for tenant {tenant_id}")
        await self.global_repo.delete_as2_identity(tenant_id, partner_id)

    async def update_as2_partner(
        self, tenant_id: int, partner_id: UUID, cmd: UpdateAS2TradingPartnerCmd
    ) -> PartnerEntity:
        if not self.global_repo:
            raise ValueError("Control plane repository is required for AS2 partner updates")
        logger.info(f"Updating AS2 partner {partner_id} for tenant {tenant_id}")
        await self.global_repo.update_as2_identity(tenant_id, partner_id, cmd)

        updated_partner = await self.global_repo.get_as2_partner(tenant_id, partner_id)
        if not updated_partner:
            raise ValueError("Partner not found after update")

        return PartnerEntity(
            partner_id=partner_id,
            tenant_id=tenant_id,
            type="AS2",
            status="ACTIVE" if updated_partner.active else "INACTIVE",
        )

    async def create_sftp_partner(self, tenant_id: int, cmd: CreateSFTPPartnerCmd) -> PartnerEntity:
        logger.info(f"Creating SFTP partner {cmd.name} for tenant {tenant_id}")

        # Written directly to Tenant DB
        partner_id = await self.tenant_repo.create_sftp_partner(cmd=cmd)

        return PartnerEntity(
            partner_id=partner_id,
            tenant_id=tenant_id,
            type="SFTP",
            status="INACTIVE",
        )

    async def update_sftp_partner(
        self, tenant_id: int, partner_id: UUID, cmd: UpdateSFTPPartnerCmd
    ) -> PartnerEntity:
        logger.info(f"Updating SFTP partner {partner_id} for tenant {tenant_id}")
        await self.tenant_repo.update_sftp_partner(partner_id=partner_id, cmd=cmd)
        updated = await self.tenant_repo.get_sftp_partner(partner_id)
        if not updated:
            raise ValueError(f"SFTP partner {partner_id} not found")

        return PartnerEntity(
            partner_id=partner_id,
            tenant_id=tenant_id,
            type="SFTP",
            status="ACTIVE" if updated.active else "INACTIVE",
        )

    async def create_as2_partnership(
        self, tenant_id: int, cmd: CreateAS2PartnershipCmd
    ) -> PartnerEntity:
        if not self.global_repo:
            raise ValueError("Control plane repository is required for AS2 partnership creation")

        local_partner = await self.global_repo.get_as2_partner(tenant_id, cmd.local_partner_id)
        if not local_partner:
            raise ValueError(f"Local AS2 partner {cmd.local_partner_id} not found")

        remote_partner = await self.global_repo.get_as2_partner(tenant_id, cmd.remote_partner_id)
        if not remote_partner:
            raise ValueError(f"Remote AS2 partner {cmd.remote_partner_id} not found")

        logger.info(
            f"Provisioning AS2 partnership {cmd.local_partner_id} -> {cmd.remote_partner_id}"
        )
        partner_id = await self.global_repo.create_as2_partnership(tenant_id=tenant_id, cmd=cmd)

        return PartnerEntity(
            partner_id=partner_id,
            tenant_id=tenant_id,
            type="AS2_PARTNERSHIP",
            status="INACTIVE",
        )

    async def update_as2_partnership(
        self, tenant_id: int, partnership_id: UUID, cmd: UpdateAS2PartnershipCmd
    ) -> PartnerEntity:
        if not self.global_repo:
            raise ValueError("Control plane repository is required for AS2 partnership update")

        logger.info(f"Updating AS2 partnership {partnership_id}")
        await self.global_repo.update_as2_partnership(
            tenant_id=tenant_id, partnership_id=partnership_id, cmd=cmd
        )
        updated = await self.global_repo.get_as2_partnership(tenant_id, partnership_id)
        if not updated:
            raise ValueError(f"AS2 partnership {partnership_id} not found")

        return PartnerEntity(
            partner_id=partnership_id,
            tenant_id=tenant_id,
            type="AS2_PARTNERSHIP",
            status="ACTIVE" if updated.active else "INACTIVE",
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
            status="INACTIVE",
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
