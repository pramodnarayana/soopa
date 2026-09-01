import dataclasses

import structlog

from edi.application.dto import UNSET, UpdateAS2PartnershipCmd
from edi.domain.events import EdiEventType, ProvisioningEvent
from edi.domain.models.as2 import AS2PartnershipDomainModel
from edi.ports.outbound.uow import ControlPlaneUnitOfWorkPort as ControlPlaneUnitOfWork

logger = structlog.get_logger(__name__)


class UpdateAS2PartnershipUseCase:
    def __init__(self, uow: ControlPlaneUnitOfWork) -> None:
        self.uow = uow

    async def update_as2_partnership(
        self, tenant_id: str, partnership_id: str, cmd: UpdateAS2PartnershipCmd
    ) -> AS2PartnershipDomainModel:
        logger.info(
            "edi_as2_partnership_update_started",
            partnership_id=partnership_id,
            tenant_id=tenant_id,
        )

        aggregate = await self.uow.as2_partnerships.get_as2_partnership(tenant_id, partnership_id)
        if not aggregate:
            raise ValueError(f"AS2 partnership {partnership_id} not found")

        for field in dataclasses.fields(cmd):
            value = getattr(cmd, field.name)
            if value is not UNSET:
                setattr(aggregate, field.name, value)

        aggregate.add_domain_event(
            ProvisioningEvent(
                tenant_id=tenant_id,
                event_type=EdiEventType.edi_as2_partnership_updated,
                resource_id=str(partnership_id),
            )
        )

        await self.uow.as2_partnerships.save(aggregate)

        logger.info(
            "edi_as2_partnership_updated",
            partnership_id=partnership_id,
            tenant_id=tenant_id,
        )

        return aggregate
