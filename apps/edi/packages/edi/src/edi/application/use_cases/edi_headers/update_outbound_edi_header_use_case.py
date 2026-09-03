import dataclasses
from datetime import UTC, datetime

import structlog
from seedwork.domain.types import UNSET

from edi.application.dtos.commands import UpdateOutboundEdiHeaderCmd
from edi.domain.events import EdiEventType, ProvisioningEvent
from edi.domain.models.headers import OutboundEdiHeaderDomainModel
from edi.ports.outbound.uow import ControlPlaneUnitOfWorkPort as ControlPlaneUnitOfWork

logger = structlog.get_logger(__name__)


class UpdateOutboundEdiHeaderUseCase:
    def __init__(self, uow: ControlPlaneUnitOfWork) -> None:
        self.uow = uow

    async def update_outbound_edi_header(
        self, tenant_id: str, header_id: str, cmd: UpdateOutboundEdiHeaderCmd
    ) -> bool:
        logger.info(
            "outbound_edi_header_update_started",
            header_id=header_id,
            tenant_id=tenant_id,
        )
        aggregate = await self.uow.edi_headers.get_outbound_edi_header(tenant_id, header_id)
        if not aggregate:
            return False

        persisted_fields = {
            field.name for field in dataclasses.fields(OutboundEdiHeaderDomainModel)
        }
        for field in dataclasses.fields(cmd):
            value = getattr(cmd, field.name)
            if value is not UNSET:
                if field.name not in persisted_fields:
                    raise ValueError(f"Unsupported outbound EDI header field: {field.name}")
                setattr(aggregate, field.name, value)
        aggregate.updated_at = datetime.now(UTC).replace(tzinfo=None)

        aggregate.add_domain_event(
            ProvisioningEvent(
                tenant_id=tenant_id,
                event_type=EdiEventType.edi_header_updated,
                resource_id=header_id,
            )
        )

        await self.uow.edi_headers.save(aggregate)
        logger.info(
            "outbound_edi_header_updated",
            header_id=header_id,
            tenant_id=tenant_id,
        )
        return True
