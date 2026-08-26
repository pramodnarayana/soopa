import structlog

from edi.application.dto import (
    UpdateAS2TradingPartnerCmd,
)
from edi.domain.events import EdiEventType, ProvisioningEvent
from edi.domain.exceptions import PartnerNotFoundError
from edi.domain.models import (
    AS2PartnerDomainModel,
)
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
        await self.uow.as2_partners.update_as2_identity(tenant_id, partner_id, cmd)

        updated_partner = await self.uow.as2_partners.get_as2_partner(tenant_id, partner_id)
        if not updated_partner:
            raise PartnerNotFoundError(partner_id, tenant_id)

        await self.uow.control_plane_outbox.publish_outbox_event(
            ProvisioningEvent(
                tenant_id=tenant_id,
                event_type=EdiEventType.edi_as2_partner_updated,
                resource_id=str(partner_id),
            ),
            idempotency_key=idempotency_key,
        )

        logger.info(
            "update_as2_partner_completed",
            id=partner_id,
            tenant_id=tenant_id,
        )

        return updated_partner
