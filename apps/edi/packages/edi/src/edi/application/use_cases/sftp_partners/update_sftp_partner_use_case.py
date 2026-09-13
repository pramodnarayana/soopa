import dataclasses

import structlog
from seedwork.constants import SystemIdPrefix
from seedwork.domain.types import UNSET, UnsetType
from seedwork.utils import generate_id

from edi.domain.enums import EdiEventType
from edi.domain.events import ProvisioningEvent
from edi.domain.models.sftp import SFTPPartnerDomainModel
from edi.ports.outbound.field_encryption import FieldEncryptionPort
from edi.ports.outbound.uow import ControlPlaneUnitOfWorkPort as ControlPlaneUnitOfWork

logger = structlog.get_logger(__name__)


@dataclasses.dataclass(frozen=True)
class UpdateSFTPPartnerCmd:
    name: str | UnsetType = UNSET
    host: str | UnsetType = UNSET
    username: str | UnsetType = UNSET
    password: str | UnsetType | None = UNSET
    credentials_vault_ref: str | UnsetType = UNSET
    port: int | UnsetType = UNSET
    inbound_remote_path: str | UnsetType | None = UNSET
    outbound_remote_path: str | UnsetType | None = UNSET
    active: bool | UnsetType = UNSET


class UpdateSFTPPartnerUseCase:
    def __init__(self, uow: ControlPlaneUnitOfWork, field_encryption: FieldEncryptionPort) -> None:
        self.uow = uow
        self.field_encryption = field_encryption

    async def update_sftp_partner(  # noqa: C901
        self,
        tenant_id: str,
        partner_id: str,
        cmd: UpdateSFTPPartnerCmd,
        idempotency_key: str | None = None,
    ) -> SFTPPartnerDomainModel:
        logger.info(
            "sftp_partner_update_started",
            partner_id=partner_id,
            tenant_id=tenant_id,
        )
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

        if not isinstance(cmd.name, UnsetType):
            existing.name = cmd.name
        if not isinstance(cmd.host, UnsetType):
            existing.host = cmd.host
        if not isinstance(cmd.username, UnsetType):
            existing.username = cmd.username
        if not isinstance(cmd.password, UnsetType):
            existing.password_encrypted = (
                self.field_encryption.encrypt(cmd.password) if cmd.password else None
            )
        if not isinstance(cmd.credentials_vault_ref, UnsetType):
            existing.credentials_vault_ref = cmd.credentials_vault_ref
        if not isinstance(cmd.port, UnsetType):
            existing.port = cmd.port
        if not isinstance(cmd.inbound_remote_path, UnsetType):
            existing.inbound_remote_path = cmd.inbound_remote_path
        if not isinstance(cmd.outbound_remote_path, UnsetType):
            existing.outbound_remote_path = cmd.outbound_remote_path
        if not isinstance(cmd.active, UnsetType):
            existing.active = cmd.active

        existing.add_domain_event(
            ProvisioningEvent(
                tenant_id=tenant_id,
                event_type=EdiEventType.edi_sftp_partner_updated,
                resource_id=partner_id,
                idempotency_key=idempotency_key or generate_id(SystemIdPrefix.GENERIC),
            )
        )

        await self.uow.sftp_partners.save(existing)

        logger.info(
            "sftp_partner_updated",
            partner_id=partner_id,
            tenant_id=tenant_id,
        )
        return existing
