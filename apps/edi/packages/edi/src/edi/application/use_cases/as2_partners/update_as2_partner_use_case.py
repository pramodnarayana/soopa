import dataclasses

import structlog

from edi.application.dto import (
    UNSET,
    UpdateAS2TradingPartnerCmd,
)
from edi.domain.events import EdiEventType, ProvisioningEvent
from edi.domain.exceptions import PartnerNotFoundError
from edi.domain.models.as2 import AS2PartnerDomainModel
from edi.ports.outbound.uow import ControlPlaneUnitOfWorkPort

logger = structlog.get_logger(__name__)


class UpdateAS2PartnerUseCase:
    """
    Use Case for updating an existing AS2 Trading Partner.
    """

    def __init__(self, uow: ControlPlaneUnitOfWorkPort) -> None:
        self.uow = uow

    async def execute(
        self,
        tenant_id: str,
        partner_id: str,
        cmd: UpdateAS2TradingPartnerCmd,
        idempotency_key: str | None = None,
    ) -> AS2PartnerDomainModel:
        logger.info(
            "update_as2_partner_started",
            id=partner_id,
            tenant_id=tenant_id,
        )
        aggregate = await self.uow.as2_partners.get_as2_partner(tenant_id, partner_id)
        if not aggregate:
            raise PartnerNotFoundError(partner_id, tenant_id)

        for field in dataclasses.fields(cmd):
            value = getattr(cmd, field.name)
            if value is not UNSET:
                setattr(aggregate, field.name, value)

        aggregate.add_domain_event(
            ProvisioningEvent(
                tenant_id=tenant_id,
                event_type=EdiEventType.edi_as2_partner_updated,
                resource_id=partner_id,
                explicit_idempotency_key=idempotency_key,
            )
        )

        await self.uow.as2_partners.save(aggregate)

        logger.info(
            "update_as2_partner_completed",
            id=partner_id,
            tenant_id=tenant_id,
        )

        return aggregate
