from dataclasses import dataclass

import structlog
from seedwork.domain.exceptions import Result
from seedwork.domain.types import UNSET, UnsetType

from edi.domain.exceptions import (
    EdiError,
    PartnerAlreadyExistsEdiError,
    PartnerAlreadyExistsError,
    PartnerNotFoundEdiError,
)
from edi.domain.partner.as2.partner import AS2Partner
from edi.ports.outbound.uow import ControlPlaneUnitOfWorkPort

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class UpdateAS2TradingPartnerCmd:
    name: str | UnsetType = UNSET
    as2_id: str | UnsetType = UNSET
    is_local: bool | UnsetType = UNSET
    url: str | UnsetType | None = UNSET
    public_cert_pem: str | UnsetType | None = UNSET
    public_cert_vault_ref: str | UnsetType | None = UNSET
    private_key_vault_ref: str | UnsetType | None = UNSET
    active: bool | UnsetType = UNSET


class UpdateAS2PartnerUseCase:
    """Use Case for updating an existing AS2 Trading Partner."""

    def __init__(self, uow: ControlPlaneUnitOfWorkPort) -> None:
        self.uow = uow

    async def execute(
        self,
        tenant_id: str,
        partner_id: str,
        cmd: UpdateAS2TradingPartnerCmd,
        idempotency_key: str | None = None,
    ) -> Result[AS2Partner, EdiError]:
        logger.info(
            "update_as2_partner_started",
            id=partner_id,
            tenant_id=tenant_id,
        )
        aggregate = await self.uow.as2_partners.get_as2_partner(tenant_id, partner_id)
        if not aggregate:
            not_found = PartnerNotFoundEdiError.for_id(partner_id, tenant_id)
            logger.error(
                "update_as2_partner_not_found",
                id=partner_id,
                tenant_id=tenant_id,
                error_code=not_found.code,
            )
            return Result.fail(not_found)

        upd_res = aggregate.update(
            name=cmd.name,
            as2_id=cmd.as2_id,
            is_local=cmd.is_local,
            url=cmd.url,
            public_cert_pem=cmd.public_cert_pem,
            public_cert_vault_ref=cmd.public_cert_vault_ref,
            private_key_vault_ref=cmd.private_key_vault_ref,
            active=cmd.active,
            idempotency_key=idempotency_key,
        )
        if upd_res.is_err:
            domain_err = upd_res.unwrap_err()
            logger.error(
                "update_as2_partner_validation_failed",
                id=partner_id,
                tenant_id=tenant_id,
                error_code=domain_err.code,
                reason=domain_err.message,
            )
            return Result.fail(domain_err)

        try:
            await self.uow.as2_partners.save(aggregate)
        except PartnerAlreadyExistsError:
            exists_err = PartnerAlreadyExistsEdiError.for_as2_id(aggregate.as2_id, tenant_id)
            logger.error(
                "update_as2_partner_conflict",
                id=partner_id,
                as2_id=aggregate.as2_id,
                tenant_id=tenant_id,
                error_code=exists_err.code,
            )
            return Result.fail(exists_err)

        logger.info(
            "update_as2_partner_completed",
            id=partner_id,
            tenant_id=tenant_id,
            final_active_status=aggregate.active,
        )

        return Result.ok(aggregate)
