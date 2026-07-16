import logging
import uuid
from uuid import UUID

from api.core.uow import UnitOfWork
from api.domain.models import (
    UNSET,
    CreateSFTPPartnerCmd,
    PartnerEntity,
    UpdateSFTPPartnerCmd,
)
from domain.events import ProvisioningEventType
from domain.models import ConnectionType, PartnerStatus

logger = logging.getLogger(__name__)


class SFTPPartnerService:
    """
    Domain service responsible for the lifecycle of SFTP Partners.
    """

    def __init__(self, uow: UnitOfWork) -> None:
        self.uow = uow

    async def create_sftp_partner(self, tenant_id: int, cmd: CreateSFTPPartnerCmd) -> PartnerEntity:
        logger.info(f"Creating SFTP partner {cmd.name} for tenant {tenant_id}")
        partner_id = await self.uow.sftp_partners.create_sftp_partner(tenant_id=tenant_id, cmd=cmd)
        await self.uow.outbox.publish_outbox_event(
            tenant_id=tenant_id,
            event_type=ProvisioningEventType.SFTP_PARTNER_CREATED,
            payload={"partner_id": str(partner_id), "tenant_id": tenant_id},
            idempotency_key=uuid.uuid5(partner_id, "SFTP_PARTNER_CREATED"),
        )

        return PartnerEntity(
            partner_id=partner_id,
            tenant_id=tenant_id,
            name=cmd.name,
            type=ConnectionType.SFTP,
            status=PartnerStatus.INACTIVE,
        )

    async def update_sftp_partner(
        self, tenant_id: int, partner_id: UUID, cmd: UpdateSFTPPartnerCmd
    ) -> PartnerEntity:
        logger.info(f"Updating SFTP partner {partner_id} for tenant {tenant_id}")
        existing = await self.uow.sftp_partners.get_sftp_partner(tenant_id, partner_id)
        if not existing:
            raise ValueError(f"SFTP partner {partner_id} not found")

        has_password = (
            bool(cmd.password) if cmd.password is not UNSET else bool(existing.password_encrypted)
        )
        has_vault = (
            bool(cmd.credentials_vault_ref)
            if cmd.credentials_vault_ref is not UNSET
            else bool(existing.credentials_vault_ref)
        )

        if not has_password and not has_vault:
            raise ValueError("SFTP partner must have either a password or a credentials_vault_ref")

        if has_password and has_vault:
            raise ValueError("SFTP partner cannot have both a password and a credentials_vault_ref")

        await self.uow.sftp_partners.update_sftp_partner(
            tenant_id=tenant_id, partner_id=partner_id, cmd=cmd
        )

        update_hash = str(hash(str(cmd)))
        await self.uow.outbox.publish_outbox_event(
            tenant_id=tenant_id,
            event_type=ProvisioningEventType.SFTP_PARTNER_UPDATED,
            payload={"partner_id": str(partner_id), "tenant_id": tenant_id},
            idempotency_key=uuid.uuid5(partner_id, f"SFTP_PARTNER_UPDATED-{update_hash}"),
        )
        updated_partner = await self.uow.sftp_partners.get_sftp_partner(tenant_id, partner_id)
        if not updated_partner:
            raise ValueError(f"SFTP partner {partner_id} not found")

        return PartnerEntity(
            partner_id=partner_id,
            tenant_id=tenant_id,
            name=str(cmd.name)
            if (cmd.name is not UNSET and cmd.name)
            else str(updated_partner.name),
            type=ConnectionType.SFTP,
            status=PartnerStatus.ACTIVE if updated_partner.active else PartnerStatus.INACTIVE,
        )
