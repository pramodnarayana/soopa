import logging
from uuid import UUID

from api.core.uow import UnitOfWork
from api.domain.models import (
    CreateAS2TradingPartnerCmd,
    PartnerEntity,
    UpdateAS2TradingPartnerCmd,
)
from domain.events import ProvisioningEventType

logger = logging.getLogger(__name__)


class AS2PartnerService:
    """
    Domain service responsible for the lifecycle of AS2 Trading Partners.
    Operates exclusively on the Global Control Plane repository.
    """

    def __init__(self, uow: UnitOfWork) -> None:
        self.uow = uow

    async def create_as2_partner(
        self, tenant_id: int, cmd: CreateAS2TradingPartnerCmd
    ) -> PartnerEntity:
        logger.info(f"Provisioning AS2 partner {cmd.name} for tenant {tenant_id}")

        partner_id = await self.uow.control_plane.create_as2_identity(tenant_id=tenant_id, cmd=cmd)
        await self.uow.control_plane.publish_outbox_event(
            tenant_id=tenant_id,
            event_type=ProvisioningEventType.AS2_PARTNER_CREATED,
            payload={"partner_id": str(partner_id), "tenant_id": tenant_id},
            idempotency_key=partner_id,
        )

        return PartnerEntity(
            partner_id=partner_id,
            tenant_id=tenant_id,
            name=cmd.name,
            type="AS2",
            status="PROVISIONING",
        )

    async def update_as2_partner(
        self, tenant_id: int, partner_id: UUID, cmd: UpdateAS2TradingPartnerCmd
    ) -> PartnerEntity:
        logger.info(f"Updating AS2 partner {partner_id} for tenant {tenant_id}")
        await self.uow.control_plane.update_as2_identity(tenant_id, partner_id, cmd)

        updated_partner = await self.uow.control_plane.get_as2_partner(tenant_id, partner_id)
        if not updated_partner:
            raise ValueError("Partner not found after update")

        await self.uow.control_plane.publish_outbox_event(
            tenant_id=tenant_id,
            event_type=ProvisioningEventType.AS2_PARTNER_UPDATED,
            payload={"partner_id": str(partner_id), "tenant_id": tenant_id},
            idempotency_key=partner_id,
        )

        return PartnerEntity(
            partner_id=partner_id,
            tenant_id=tenant_id,
            name=cmd.name or updated_partner.name,
            type="AS2",
            status="ACTIVE" if updated_partner.active else "INACTIVE",
        )

    async def delete_as2_partner(self, tenant_id: int, partner_id: UUID) -> None:
        logger.info(f"Deleting AS2 partner {partner_id} for tenant {tenant_id}")
        await self.uow.control_plane.delete_as2_identity(tenant_id, partner_id)
        await self.uow.control_plane.publish_outbox_event(
            tenant_id=tenant_id,
            event_type=ProvisioningEventType.AS2_PARTNER_DELETED,
            payload={"partner_id": str(partner_id), "tenant_id": tenant_id},
            idempotency_key=partner_id,
        )

    async def rotate_certificates(
        self,
        tenant_id: int,
        partner_id: UUID,
        new_public_cert: str,
        new_private_key_vault_ref: str | None,
    ) -> PartnerEntity:
        logger.info(f"Rotating certificates for AS2 partner {partner_id} for tenant {tenant_id}")
        await self.uow.control_plane.rotate_as2_certificates(
            tenant_id, partner_id, new_public_cert, new_private_key_vault_ref
        )

        updated_partner = await self.uow.control_plane.get_as2_partner(tenant_id, partner_id)
        if not updated_partner:
            raise ValueError("Partner not found after certificate rotation")

        await self.uow.control_plane.publish_outbox_event(
            tenant_id=tenant_id,
            event_type=ProvisioningEventType.AS2_PARTNER_UPDATED,
            payload={"partner_id": str(partner_id), "tenant_id": tenant_id},
            idempotency_key=partner_id,
        )

        return PartnerEntity(
            partner_id=partner_id,
            tenant_id=tenant_id,
            name=updated_partner.name,
            type="AS2",
            status="ACTIVE" if updated_partner.active else "INACTIVE",
        )
