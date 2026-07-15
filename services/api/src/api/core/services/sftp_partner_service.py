import logging
from uuid import UUID

from api.core.uow import UnitOfWork
from api.domain.models import (
    UNSET,
    CreateSFTPPartnerCmd,
    PartnerEntity,
    UpdateSFTPPartnerCmd,
)
from domain.events import ProvisioningEventType

logger = logging.getLogger(__name__)


class SFTPPartnerService:
    """
    Domain service responsible for the lifecycle of SFTP Partners.
    """

    def __init__(self, uow: UnitOfWork) -> None:
        self.uow = uow

    async def create_sftp_partner(self, tenant_id: int, cmd: CreateSFTPPartnerCmd) -> PartnerEntity:
        logger.info(f"Creating SFTP partner {cmd.name} for tenant {tenant_id}")
        partner_id = await self.uow.control_plane.create_sftp_partner(tenant_id=tenant_id, cmd=cmd)
        await self.uow.control_plane.publish_outbox_event(
            tenant_id=tenant_id,
            event_type=ProvisioningEventType.SFTP_PARTNER_CREATED,
            payload={"partner_id": str(partner_id), "tenant_id": tenant_id},
            idempotency_key=partner_id,
        )

        return PartnerEntity(
            partner_id=partner_id,
            tenant_id=tenant_id,
            name=cmd.name,
            type="SFTP",
            status="INACTIVE",
        )

    async def update_sftp_partner(
        self, tenant_id: int, partner_id: UUID, cmd: UpdateSFTPPartnerCmd
    ) -> PartnerEntity:
        logger.info(f"Updating SFTP partner {partner_id} for tenant {tenant_id}")
        await self.uow.control_plane.update_sftp_partner(
            tenant_id=tenant_id, partner_id=partner_id, cmd=cmd
        )
        await self.uow.control_plane.publish_outbox_event(
            tenant_id=tenant_id,
            event_type=ProvisioningEventType.SFTP_PARTNER_UPDATED,
            payload={"partner_id": str(partner_id), "tenant_id": tenant_id},
            idempotency_key=partner_id,
        )
        updated = await self.uow.control_plane.get_sftp_partner(tenant_id, partner_id)
        if not updated:
            raise ValueError(f"SFTP partner {partner_id} not found")

        return PartnerEntity(
            partner_id=partner_id,
            tenant_id=tenant_id,
            name=str(cmd.name) if (cmd.name is not UNSET and cmd.name) else str(updated.name),
            type="SFTP",
            status="ACTIVE" if updated.active else "INACTIVE",
        )
