import structlog

from edi.application.dto import (
    UNSET,
    CreateSFTPPartnerCmd,
    UpdateSFTPPartnerCmd,
)
from edi.domain.events import EdiEventType, ProvisioningEvent
from edi.domain.models import (
    SFTPPartnerDomainModel,
)
from edi.ports.outbound.uow import ControlPlaneUnitOfWorkPort as ControlPlaneUnitOfWork

logger = structlog.get_logger(__name__)


class SFTPPartnerService:
    """
    Domain service responsible for the lifecycle of SFTP Partners.
    """

    def __init__(self, uow: ControlPlaneUnitOfWork) -> None:
        self.uow = uow

    async def create_sftp_partner(
        self, tenant_id: str, cmd: CreateSFTPPartnerCmd, idempotency_key: str | None = None
    ) -> SFTPPartnerDomainModel:
        logger.info(
            "Creating SFTP partner {cmd.name} for tenant {tenant_id}",
            cmd_name=cmd.name,
            tenant_id=tenant_id,
        )
        partner_id = await self.uow.sftp_partners.create_sftp_partner(tenant_id=tenant_id, cmd=cmd)
        await self.uow.control_plane_outbox.publish_outbox_event(
            event=ProvisioningEvent(
                tenant_id=tenant_id,
                event_type=EdiEventType.edi_sftp_partner_created,
                resource_id=str(partner_id),
            ),
            idempotency_key=idempotency_key,
        )

        from datetime import datetime

        return SFTPPartnerDomainModel(
            id=partner_id,
            tenant_id=tenant_id,
            name=cmd.name,
            host=cmd.host,
            port=cmd.port,
            username=cmd.username,
            active=False,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )

    async def update_sftp_partner(
        self,
        tenant_id: str,
        partner_id: str,
        cmd: UpdateSFTPPartnerCmd,
        idempotency_key: str | None = None,
    ) -> SFTPPartnerDomainModel:
        logger.info(
            "Updating SFTP partner {partner_id} for tenant {tenant_id}",
            partner_id=partner_id,
            tenant_id=tenant_id,
        )
        existing = await self.uow.sftp_partners.get_sftp_partner(tenant_id, partner_id)
        if not existing:
            raise ValueError(f"SFTP partner {partner_id} not found")

        has_password = (
            bool(getattr(cmd, "password", None))
            if getattr(cmd, "password", None) is not UNSET
            else bool(getattr(existing, "password_encrypted", None))
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

        await self.uow.control_plane_outbox.publish_outbox_event(
            event=ProvisioningEvent(
                tenant_id=tenant_id,
                event_type=EdiEventType.edi_sftp_partner_updated,
                resource_id=str(partner_id),
            ),
            idempotency_key=idempotency_key,
        )
        updated_partner = await self.uow.sftp_partners.get_sftp_partner(tenant_id, partner_id)
        if not updated_partner:
            raise ValueError(f"SFTP partner {partner_id} not found")

        from datetime import datetime

        return SFTPPartnerDomainModel(
            id=partner_id,
            tenant_id=tenant_id,
            name=str(cmd.name)
            if (cmd.name is not UNSET and cmd.name)
            else str(updated_partner.name),
            host=updated_partner.host,
            port=updated_partner.port,
            username=updated_partner.username,
            active=updated_partner.active,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )

    async def delete_sftp_partner(
        self, tenant_id: str, partner_id: str, idempotency_key: str | None = None
    ) -> None:
        logger.info(
            "Deleting SFTP partner {partner_id} for tenant {tenant_id}",
            partner_id=partner_id,
            tenant_id=tenant_id,
        )
        await self.uow.sftp_partners.delete_sftp_partner(tenant_id, partner_id)

        await self.uow.control_plane_outbox.publish_outbox_event(
            ProvisioningEvent(
                tenant_id=tenant_id,
                event_type=EdiEventType.edi_sftp_partner_deleted,
                resource_id=str(partner_id),
            ),
            idempotency_key=idempotency_key,
        )
