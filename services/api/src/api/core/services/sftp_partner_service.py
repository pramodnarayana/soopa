import logging
from uuid import UUID

from api.domain.models import (
    CreateSFTPPartnerCmd,
    PartnerEntity,
    UpdateSFTPPartnerCmd,
)
from api.ports.repository import ControlPlaneRepositoryPort
from domain.events import ProvisioningEventType

logger = logging.getLogger(__name__)


class SFTPPartnerService:
    """
    Domain service responsible for the lifecycle of SFTP Partners.
    """

    def __init__(self, global_repo: ControlPlaneRepositoryPort) -> None:
        self.global_repo = global_repo

    async def create_sftp_partner(self, tenant_id: int, cmd: CreateSFTPPartnerCmd) -> PartnerEntity:
        logger.info(f"Creating SFTP partner {cmd.name} for tenant {tenant_id}")
        partner_id = await self.global_repo.create_sftp_partner(tenant_id=tenant_id, cmd=cmd)
        await self.global_repo.create_outbox_event(
            tenant_id=tenant_id,
            event_type=ProvisioningEventType.SFTP_PARTNER_CREATED,
            payload={"partner_id": str(partner_id), "tenant_id": tenant_id},
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
        await self.global_repo.update_sftp_partner(
            tenant_id=tenant_id, partner_id=partner_id, cmd=cmd
        )
        await self.global_repo.create_outbox_event(
            tenant_id=tenant_id,
            event_type=ProvisioningEventType.SFTP_PARTNER_UPDATED,
            payload={"partner_id": str(partner_id), "tenant_id": tenant_id},
        )
        updated = await self.global_repo.get_sftp_partner(tenant_id, partner_id)
        if not updated:
            raise ValueError(f"SFTP partner {partner_id} not found")

        return PartnerEntity(
            partner_id=partner_id,
            tenant_id=tenant_id,
            name=cmd.name or updated.name,
            type="SFTP",
            status="ACTIVE" if updated.active else "INACTIVE",
        )
