import hashlib
import logging
import uuid

from domain.events import ProvisioningEvent
from domain.models import ConnectionType, PartnerStatus
from soopa_schemas.edi_events import EdiEventType

from api.core.uow import ControlPlaneUnitOfWork
from api.domain.models import (
    UNSET,
    CreateSFTPPartnerCmd,
    PartnerEntity,
    UpdateSFTPPartnerCmd,
)

logger = logging.getLogger(__name__)


class SFTPPartnerService:
    """
    Domain service responsible for the lifecycle of SFTP Partners.
    """

    def __init__(self, uow: ControlPlaneUnitOfWork) -> None:
        self.uow = uow

    async def create_sftp_partner(self, tenant_id: str, cmd: CreateSFTPPartnerCmd) -> PartnerEntity:
        logger.info(f"Creating SFTP partner {cmd.name} for tenant {tenant_id}")
        partner_id = await self.uow.sftp_partners.create_sftp_partner(tenant_id=tenant_id, cmd=cmd)
        await self.uow.control_plane_outbox.publish_outbox_event(
            event=ProvisioningEvent(
                tenant_id=tenant_id,
                event_type=EdiEventType.edi_sftp_partner_created,
                resource_id=str(partner_id),
            ),
            idempotency_key=str(
                uuid.uuid5(uuid.NAMESPACE_DNS, f"{partner_id}-SFTP_PARTNER_CREATED")
            ),
        )

        return PartnerEntity(
            partner_id=partner_id,
            tenant_id=tenant_id,
            name=cmd.name,
            type=ConnectionType.SFTP,
            status=PartnerStatus.INACTIVE,
        )

    async def update_sftp_partner(
        self, tenant_id: str, partner_id: str, cmd: UpdateSFTPPartnerCmd
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

        update_hash = hashlib.sha256(str(cmd).encode()).hexdigest()
        await self.uow.control_plane_outbox.publish_outbox_event(
            event=ProvisioningEvent(
                tenant_id=tenant_id,
                event_type=EdiEventType.edi_sftp_partner_updated,
                resource_id=str(partner_id),
            ),
            idempotency_key=str(
                uuid.uuid5(uuid.NAMESPACE_DNS, f"{partner_id}-SFTP_PARTNER_UPDATED-{update_hash}")
            ),
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
