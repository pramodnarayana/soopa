import dataclasses

import structlog
from seedwork.domain.types import UNSET

from edi.application.dtos.commands import UpdateSFTPPartnerCmd
from edi.domain.enums import EdiEventType
from edi.domain.events import ProvisioningEvent
from edi.domain.models.sftp import SFTPPartnerDomainModel
from edi.ports.outbound.field_encryption import FieldEncryptionPort
from edi.ports.outbound.uow import ControlPlaneUnitOfWorkPort as ControlPlaneUnitOfWork

logger = structlog.get_logger(__name__)


class UpdateSFTPPartnerUseCase:
    def __init__(self, uow: ControlPlaneUnitOfWork, field_encryption: FieldEncryptionPort) -> None:
        self.uow = uow
        self.field_encryption = field_encryption

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
            bool(cmd.password)
            if cmd.password is not UNSET
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

        persisted_fields = {field.name for field in dataclasses.fields(SFTPPartnerDomainModel)}
        for field in dataclasses.fields(cmd):
            value = getattr(cmd, field.name)
            if value is not UNSET:
                if field.name == "password":
                    existing.password_encrypted = (
                        self.field_encryption.encrypt(value) if value else None
                    )
                elif field.name in persisted_fields:
                    setattr(existing, field.name, value)
                else:
                    raise ValueError(f"Unsupported SFTP partner field: {field.name}")

        existing.add_domain_event(
            ProvisioningEvent(
                tenant_id=tenant_id,
                event_type=EdiEventType.edi_sftp_partner_updated,
                resource_id=partner_id,
                explicit_idempotency_key=idempotency_key,
            )
        )

        await self.uow.sftp_partners.save(existing)

        logger.info(
            "sftp_partner_updated",
            partner_id=partner_id,
            tenant_id=tenant_id,
        )
        return existing
