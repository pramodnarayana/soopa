from dataclasses import dataclass

import structlog
from seedwork.domain.exceptions import Result
from seedwork.domain.types import UNSET, JsonValue, UnsetType

from edi.domain.exceptions import (
    EdiError,
    EdiValidationError,
    PartnershipAlreadyExistsError,
    PartnershipNotFoundEdiError,
)
from edi.domain.partner.as2.enums import EncryptionAlgorithm, MDNType, SignatureAlgorithm
from edi.domain.partner.as2.partnership import AS2Partnership
from edi.ports.outbound.uow import ControlPlaneUnitOfWorkPort as ControlPlaneUnitOfWork

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class UpdateAS2PartnershipCmd:
    name: str | UnsetType | None = UNSET
    credentials_vault_ref: str | UnsetType | None = UNSET
    mdn_type: MDNType | UnsetType | None = UNSET
    mdn_url: str | UnsetType | None = UNSET
    encryption_algorithm: EncryptionAlgorithm | UnsetType | None = UNSET
    signature_algorithm: SignatureAlgorithm | UnsetType | None = UNSET
    advanced_flags: dict[str, JsonValue] | UnsetType | None = UNSET
    active: bool | UnsetType | None = UNSET


class UpdateAS2PartnershipUseCase:
    def __init__(self, uow: ControlPlaneUnitOfWork) -> None:
        self.uow = uow

    async def update_as2_partnership(
        self, tenant_id: str, partnership_id: str, cmd: UpdateAS2PartnershipCmd
    ) -> Result[AS2Partnership, EdiError]:
        logger.info(
            "edi_as2_partnership_update_started",
            partnership_id=partnership_id,
            tenant_id=tenant_id,
        )

        aggregate = await self.uow.as2_partnerships.get_as2_partnership(tenant_id, partnership_id)
        if not aggregate:
            not_found = PartnershipNotFoundEdiError.for_id(partnership_id, tenant_id)
            logger.error(
                "edi_as2_partnership_not_found",
                partnership_id=partnership_id,
                tenant_id=tenant_id,
                error_code=not_found.code,
            )
            return Result.fail(not_found)

        upd_res = aggregate.update(
            name=cmd.name,
            credentials_vault_ref=cmd.credentials_vault_ref,
            mdn_type=cmd.mdn_type,
            mdn_url=cmd.mdn_url,
            encryption_algorithm=cmd.encryption_algorithm,
            signature_algorithm=cmd.signature_algorithm,
            advanced_flags=cmd.advanced_flags,
            active=cmd.active,
        )
        if upd_res.is_err:
            domain_err = upd_res.unwrap_err()
            logger.error(
                "edi_as2_partnership_update_validation_failed",
                partnership_id=partnership_id,
                tenant_id=tenant_id,
                error_code=domain_err.code,
                reason=domain_err.message,
            )
            return Result.fail(domain_err)

        try:
            await self.uow.as2_partnerships.save(aggregate)
        except PartnershipAlreadyExistsError:
            conflict_err = EdiValidationError.with_message(
                "AS2 Partnership already exists for these partners."
            )
            logger.error(
                "edi_as2_partnership_update_conflict",
                partnership_id=partnership_id,
                tenant_id=tenant_id,
                error_code=conflict_err.code,
            )
            return Result.fail(conflict_err)

        persisted = await self.uow.as2_partnerships.get_as2_partnership(tenant_id, partnership_id)
        if persisted:
            aggregate = persisted

        logger.info(
            "edi_as2_partnership_updated",
            partnership_id=partnership_id,
            tenant_id=tenant_id,
        )

        return Result.ok(aggregate)
