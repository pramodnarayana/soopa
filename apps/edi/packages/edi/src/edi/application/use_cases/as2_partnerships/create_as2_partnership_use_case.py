import os
from datetime import UTC, datetime

import structlog

from edi.application.dtos.commands import CreateAS2PartnershipCmd
from edi.domain.enums import EdiEventType
from edi.domain.events import ProvisioningEvent
from edi.domain.models.as2 import AS2PartnershipDomainModel
from edi.ports.outbound.uow import ControlPlaneUnitOfWorkPort as ControlPlaneUnitOfWork

logger = structlog.get_logger(__name__)


class CreateAS2PartnershipUseCase:
    def __init__(self, uow: ControlPlaneUnitOfWork) -> None:
        self.uow = uow

    async def create_as2_partnership(
        self, tenant_id: str, cmd: CreateAS2PartnershipCmd
    ) -> AS2PartnershipDomainModel:
        local_partner = await self.uow.as2_partners.get_as2_partner(
            tenant_id, str(cmd.local_partner_id)
        )
        if not local_partner:
            raise ValueError(f"Local AS2 partner {cmd.local_partner_id} not found")

        remote_partner = await self.uow.as2_partners.get_as2_partner(
            tenant_id, str(cmd.remote_partner_id)
        )
        if not remote_partner:
            raise ValueError(f"Remote AS2 partner {cmd.remote_partner_id} not found")

        logger.info(
            "edi_as2_partnership_creation_started",
            cmd_local_id=cmd.local_partner_id,
            cmd_remote_id=cmd.remote_partner_id,
            tenant_id=tenant_id,
        )

        partner_id = f"{AS2PartnershipDomainModel.ID_PREFIX}_{os.urandom(12).hex()}"

        aggregate = AS2PartnershipDomainModel(
            id=partner_id,
            name=cmd.name,
            local_partner_id=str(cmd.local_partner_id),
            remote_partner_id=str(cmd.remote_partner_id),
            mdn_type=cmd.mdn_type,
            encryption_algorithm=cmd.encryption_algorithm,
            signature_algorithm=cmd.signature_algorithm,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            tenant_id=tenant_id,
            active=True,
            mdn_url=cmd.mdn_url,
        )

        aggregate.add_domain_event(
            ProvisioningEvent(
                tenant_id=tenant_id,
                event_type=EdiEventType.edi_as2_partnership_created,
                resource_id=partner_id,
            )
        )

        await self.uow.as2_partnerships.save(aggregate)

        logger.info(
            "edi_as2_partnership_created",
            partnership_id=partner_id,
            tenant_id=tenant_id,
        )

        return aggregate
