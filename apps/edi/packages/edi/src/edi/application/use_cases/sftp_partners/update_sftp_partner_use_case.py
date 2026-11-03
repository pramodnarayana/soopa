import dataclasses

import structlog
from security.ports.cipher_port import CipherPort
from seedwork.domain.exceptions import Result
from seedwork.domain.types import UNSET, UnsetType

from edi.domain.exceptions import (
    EdiError,
    EdiValidationError,
    PartnerNotFoundEdiError,
    SftpPartnerAlreadyExistsError,
)
from edi.domain.partner.sftp.partner import SFTPPartner
from edi.ports.outbound.uow import ControlPlaneUnitOfWorkPort

logger = structlog.get_logger(__name__)


@dataclasses.dataclass(frozen=True)
class UpdateSFTPPartnerCmd:
    name: str | UnsetType = UNSET
    host: str | UnsetType = UNSET
    username: str | UnsetType = UNSET
    password: str | UnsetType | None = UNSET
    credentials_vault_ref: str | UnsetType | None = UNSET
    port: int | UnsetType = UNSET
    inbound_remote_path: str | UnsetType | None = UNSET
    outbound_remote_path: str | UnsetType | None = UNSET
    active: bool | UnsetType = UNSET


class UpdateSFTPPartnerUseCase:
    def __init__(self, uow: ControlPlaneUnitOfWorkPort, field_encryption: CipherPort) -> None:
        self.uow = uow
        self.field_encryption = field_encryption

    async def update_sftp_partner(
        self,
        tenant_id: str,
        partner_id: str,
        cmd: UpdateSFTPPartnerCmd,
        idempotency_key: str | None = None,
    ) -> Result[SFTPPartner, EdiError]:
        logger.info(
            "sftp_partner_update_started",
            partner_id=partner_id,
            tenant_id=tenant_id,
        )
        existing = await self.uow.sftp_partners.get_sftp_partner(tenant_id, partner_id)
        if not existing:
            not_found = PartnerNotFoundEdiError.for_id(partner_id, tenant_id, protocol="SFTP")
            logger.error(
                "sftp_partner_not_found",
                partner_id=partner_id,
                tenant_id=tenant_id,
                error_code=not_found.code,
            )
            return Result.fail(not_found)

        encrypted_password: str | UnsetType | None = UNSET
        if not isinstance(cmd.password, UnsetType):
            encrypted_password = (
                self.field_encryption.encrypt_str(cmd.password) if cmd.password else None
            )

        upd_res = existing.update(
            name=cmd.name,
            host=cmd.host,
            username=cmd.username,
            port=cmd.port,
            inbound_remote_path=cmd.inbound_remote_path,
            outbound_remote_path=cmd.outbound_remote_path,
            password_encrypted=encrypted_password,
            credentials_vault_ref=cmd.credentials_vault_ref,
            active=cmd.active,
            idempotency_key=idempotency_key,
        )
        if upd_res.is_err:
            domain_err = upd_res.unwrap_err()
            logger.error(
                "sftp_partner_update_validation_failed",
                partner_id=partner_id,
                tenant_id=tenant_id,
                error_code=domain_err.code,
                reason=domain_err.message,
            )
            return Result.fail(domain_err)

        try:
            await self.uow.sftp_partners.save(existing)
        except SftpPartnerAlreadyExistsError:
            conflict_err = EdiValidationError.with_message("Database integrity error.")
            logger.error(
                "sftp_partner_update_conflict",
                partner_id=partner_id,
                tenant_id=tenant_id,
                error_code=conflict_err.code,
            )
            return Result.fail(conflict_err)

        logger.info(
            "sftp_partner_updated",
            partner_id=partner_id,
            tenant_id=tenant_id,
        )
        return Result.ok(existing)
