from dataclasses import dataclass

import structlog
from seedwork.domain.exceptions import Result
from seedwork.domain.types import JsonValue

from edi.domain.exceptions import (
    EdiError,
    EdiValidationError,
    PartnershipAlreadyExistsError,
)
from edi.domain.partner.as2.enums import EncryptionAlgorithm, MDNType, SignatureAlgorithm
from edi.domain.partner.as2.partnership import AS2Partnership
from edi.ports.outbound.uow import ControlPlaneUnitOfWorkPort as ControlPlaneUnitOfWork

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class CreateAS2PartnershipCmd:
    name: str
    local_partner_id: str
    remote_partner_id: str
    local_url: str | None = None
    remote_url: str | None = None
    credentials_vault_ref: str | None = None
    mdn_type: MDNType = MDNType.SYNC
    mdn_url: str | None = None
    encryption_algorithm: EncryptionAlgorithm = EncryptionAlgorithm.AES256
    signature_algorithm: SignatureAlgorithm = SignatureAlgorithm.SHA256
    advanced_flags: dict[str, JsonValue] | None = None


class CreateAS2PartnershipUseCase:
    def __init__(self, uow: ControlPlaneUnitOfWork) -> None:
        self.uow = uow

    async def create_as2_partnership(
        self, tenant_id: str, cmd: CreateAS2PartnershipCmd
    ) -> Result[AS2Partnership, EdiError]:
        local_partner = await self.uow.as2_partners.get_as2_partner(
            tenant_id, str(cmd.local_partner_id)
        )
        if not local_partner:
            err = EdiValidationError.with_message(
                f"Local AS2 partner {cmd.local_partner_id} not found",
                details={"local_partner_id": str(cmd.local_partner_id)},
            )
            logger.error(
                "edi_as2_partnership_local_partner_not_found",
                local_partner_id=cmd.local_partner_id,
                tenant_id=tenant_id,
                error_code=err.code,
            )
            return Result.fail(err)

        remote_partner = await self.uow.as2_partners.get_as2_partner(
            tenant_id, str(cmd.remote_partner_id)
        )
        if not remote_partner:
            err = EdiValidationError.with_message(
                f"Remote AS2 partner {cmd.remote_partner_id} not found",
                details={"remote_partner_id": str(cmd.remote_partner_id)},
            )
            logger.error(
                "edi_as2_partnership_remote_partner_not_found",
                remote_partner_id=cmd.remote_partner_id,
                tenant_id=tenant_id,
                error_code=err.code,
            )
            return Result.fail(err)

        logger.info(
            "edi_as2_partnership_creation_started",
            cmd_local_id=cmd.local_partner_id,
            cmd_remote_id=cmd.remote_partner_id,
            tenant_id=tenant_id,
        )

        create_res = AS2Partnership.create(
            tenant_id=tenant_id,
            name=cmd.name,
            local_partner_id=str(cmd.local_partner_id),
            remote_partner_id=str(cmd.remote_partner_id),
            mdn_type=cmd.mdn_type,
            encryption_algorithm=cmd.encryption_algorithm,
            signature_algorithm=cmd.signature_algorithm,
            active=True,
            mdn_url=cmd.mdn_url,
            credentials_vault_ref=cmd.credentials_vault_ref,
            advanced_flags=cmd.advanced_flags,
        )
        if create_res.is_err:
            domain_err = create_res.unwrap_err()
            logger.error(
                "edi_as2_partnership_validation_failed",
                tenant_id=tenant_id,
                error_code=domain_err.code,
                reason=domain_err.message,
            )
            return Result.fail(domain_err)

        aggregate = create_res.unwrap()
        try:
            await self.uow.as2_partnerships.save(aggregate)
        except PartnershipAlreadyExistsError:
            conflict_err = EdiValidationError.with_message(
                "AS2 Partnership already exists for these partners."
            )
            logger.error(
                "edi_as2_partnership_already_exists",
                tenant_id=tenant_id,
                local_partner_id=cmd.local_partner_id,
                remote_partner_id=cmd.remote_partner_id,
                error_code=conflict_err.code,
            )
            return Result.fail(conflict_err)

        logger.info(
            "edi_as2_partnership_created",
            partnership_id=aggregate.id,
            tenant_id=tenant_id,
        )

        return Result.ok(aggregate)
