import logging
from uuid import UUID

from domain.events import ProvisioningEventType
from domain.models import ConnectionType, PartnerStatus

from api.core.uow import UnitOfWork
from api.domain.models import (
    CreateAS2TradingPartnerCmd,
    PartnerEntity,
    UpdateAS2TradingPartnerCmd,
)

logger = logging.getLogger(__name__)


class AS2PartnerService:
    """
    Domain service responsible for the lifecycle of AS2 Trading Partners.
    Operates exclusively on the Global Control Plane repository.
    """

    def __init__(self, uow: UnitOfWork) -> None:
        self.uow = uow

    async def create_as2_partner(
        self, tenant_id: str, cmd: CreateAS2TradingPartnerCmd
    ) -> PartnerEntity:
        logger.info(f"Provisioning AS2 partner {cmd.name} for tenant {tenant_id}")

        partner_id = await self.uow.as2_partners.create_as2_identity(tenant_id=str(tenant_id), cmd=cmd)
        await self.uow.control_plane_outbox.publish_outbox_event(
            tenant_id=tenant_id,
            event_type=ProvisioningEventType.AS2_PARTNER_CREATED,
            payload={"partner_id": str(partner_id), "tenant_id": str(tenant_id)},
        )

        return PartnerEntity(
            partner_id=partner_id,
            tenant_id=str(tenant_id),
            name=cmd.name,
            type=ConnectionType.AS2,
            status=PartnerStatus.PROVISIONING,
        )

    async def update_as2_partner(
        self, tenant_id: str, partner_id: UUID, cmd: UpdateAS2TradingPartnerCmd
    ) -> PartnerEntity:
        logger.info(f"Updating AS2 partner {partner_id} for tenant {tenant_id}")
        await self.uow.as2_partners.update_as2_identity(str(tenant_id), partner_id, cmd)

        updated_partner = await self.uow.as2_partners.get_as2_partner(str(tenant_id), partner_id)
        if not updated_partner:
            raise ValueError("Partner not found after update")

        await self.uow.control_plane_outbox.publish_outbox_event(
            tenant_id=tenant_id,
            event_type=ProvisioningEventType.AS2_PARTNER_UPDATED,
            payload={"partner_id": str(partner_id), "tenant_id": str(tenant_id)},
        )

        return PartnerEntity(
            partner_id=partner_id,
            tenant_id=str(tenant_id),
            name=cmd.name or updated_partner.name,
            type=ConnectionType.AS2,
            status=PartnerStatus.ACTIVE if updated_partner.active else PartnerStatus.INACTIVE,
        )

    async def delete_as2_partner(self, tenant_id: str, partner_id: UUID) -> None:
        logger.info(f"Deleting AS2 partner {partner_id} for tenant {tenant_id}")
        await self.uow.as2_partners.delete_as2_identity(str(tenant_id), partner_id)
        await self.uow.control_plane_outbox.publish_outbox_event(
            tenant_id=tenant_id,
            event_type=ProvisioningEventType.AS2_PARTNER_DELETED,
            payload={"partner_id": str(partner_id), "tenant_id": str(tenant_id)},
        )

    async def rotate_certificates(
        self,
        tenant_id: str,
        partner_id: UUID,
        new_public_cert: str,
        new_private_key_vault_ref: str | None,
    ) -> PartnerEntity:
        logger.info(f"Rotating certificates for AS2 partner {partner_id} for tenant {tenant_id}")
        await self.uow.as2_partners.rotate_as2_certificates(
            str(tenant_id), partner_id, new_public_cert, new_private_key_vault_ref
        )

        updated_partner = await self.uow.as2_partners.get_as2_partner(str(tenant_id), partner_id)
        if not updated_partner:
            raise ValueError("Partner not found after certificate rotation")

        await self.uow.control_plane_outbox.publish_outbox_event(
            tenant_id=tenant_id,
            event_type=ProvisioningEventType.AS2_PARTNER_UPDATED,
            payload={"partner_id": str(partner_id), "tenant_id": str(tenant_id)},
        )

        return PartnerEntity(
            partner_id=partner_id,
            tenant_id=str(tenant_id),
            name=updated_partner.name,
            type=ConnectionType.AS2,
            status=PartnerStatus.ACTIVE if updated_partner.active else PartnerStatus.INACTIVE,
        )
