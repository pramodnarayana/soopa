from dataclasses import dataclass

import structlog
from security.ports.cipher_port import CipherPort
from seedwork.domain.exceptions import Result

from edi.domain.exceptions import (
    EdiError,
    EdiValidationError,
    SftpPartnerAlreadyExistsError,
)
from edi.domain.partner.sftp.partner import SFTPPartner
from edi.ports.outbound.uow import ControlPlaneUnitOfWorkPort as ControlPlaneUnitOfWork

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class CreateSFTPPartnerCmd:
    name: str
    host: str
    username: str
    credentials_vault_ref: str | None = None
    password: str | None = None
    port: int = 22
    inbound_remote_path: str | None = None
    outbound_remote_path: str | None = None


class CreateSFTPPartnerUseCase:
    def __init__(
        self,
        uow: ControlPlaneUnitOfWork,
        field_encryption: CipherPort | None = None,
    ) -> None:
        self.uow = uow
        self.field_encryption = field_encryption

    async def create_sftp_partner(
        self, tenant_id: str, cmd: CreateSFTPPartnerCmd, idempotency_key: str | None = None
    ) -> Result[SFTPPartner, EdiError]:
        logger.info(
            "sftp_partner_creation_started",
            cmd_name=cmd.name,
            tenant_id=tenant_id,
        )

        encrypted_password: str | None = None
        if cmd.password and cmd.password.strip():
            if self.field_encryption is None:
                err = EdiValidationError.with_message(
                    "Field encryption adapter is required when provisioning an SFTP partner password."
                )
                logger.error(
                    "sftp_partner_creation_missing_encryption_adapter",
                    cmd_name=cmd.name,
                    tenant_id=tenant_id,
                    error_code=err.code,
                )
                return Result.fail(err)
            encrypted_password = self.field_encryption.encrypt_str(cmd.password)

        create_res = SFTPPartner.create(
            tenant_id=tenant_id,
            name=cmd.name,
            host=cmd.host,
            port=cmd.port,
            username=cmd.username,
            inbound_remote_path=cmd.inbound_remote_path,
            outbound_remote_path=cmd.outbound_remote_path,
            password_encrypted=encrypted_password,
            credentials_vault_ref=cmd.credentials_vault_ref,
            active=False,
            idempotency_key=idempotency_key,
        )
        if create_res.is_err:
            domain_err = create_res.unwrap_err()
            logger.error(
                "sftp_partner_creation_validation_failed",
                cmd_name=cmd.name,
                tenant_id=tenant_id,
                error_code=domain_err.code,
                reason=domain_err.message,
            )
            return Result.fail(domain_err)

        aggregate = create_res.unwrap()
        try:
            await self.uow.sftp_partners.save(aggregate)
        except SftpPartnerAlreadyExistsError:
            conflict_err = EdiValidationError.with_message("Database integrity error.")
            logger.error(
                "sftp_partner_creation_conflict",
                cmd_name=cmd.name,
                tenant_id=tenant_id,
                error_code=conflict_err.code,
            )
            return Result.fail(conflict_err)

        logger.info(
            "sftp_partner_created",
            partner_id=aggregate.id,
            tenant_id=tenant_id,
        )
        return Result.ok(aggregate)
