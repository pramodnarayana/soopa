import dataclasses
from datetime import UTC, datetime

import structlog
from seedwork.domain.types import UNSET, UnsetType

from edi.domain.enums import EdiEventType
from edi.domain.events import ProvisioningEvent
from edi.ports.outbound.uow import ControlPlaneUnitOfWorkPort as ControlPlaneUnitOfWork

logger = structlog.get_logger(__name__)


@dataclasses.dataclass(frozen=True)
class UpdateOutboundEdiHeaderCmd:
    trading_partner_id: str | UnsetType = UNSET
    isa_sender_id: str | UnsetType = UNSET
    isa_receiver_id: str | UnsetType = UNSET
    name: str | UnsetType | None = UNSET
    isa_sender_qualifier: str | UnsetType | None = UNSET
    isa_receiver_qualifier: str | UnsetType | None = UNSET
    gs_sender_id: str | UnsetType | None = UNSET
    gs_receiver_id: str | UnsetType | None = UNSET
    transaction_type: str | UnsetType | None = UNSET
    default_standard: str | UnsetType | None = UNSET
    default_version: str | UnsetType | None = UNSET


class UpdateOutboundEdiHeaderUseCase:
    def __init__(self, uow: ControlPlaneUnitOfWork) -> None:
        self.uow = uow

    async def update_outbound_edi_header(  # noqa: C901
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

        if not isinstance(cmd.trading_partner_id, UnsetType):
            aggregate.trading_partner_id = cmd.trading_partner_id
        if not isinstance(cmd.isa_sender_id, UnsetType):
            aggregate.isa_sender_id = cmd.isa_sender_id
        if not isinstance(cmd.isa_receiver_id, UnsetType):
            aggregate.isa_receiver_id = cmd.isa_receiver_id
        if not isinstance(cmd.name, UnsetType):
            aggregate.name = cmd.name
        if not isinstance(cmd.isa_sender_qualifier, UnsetType):
            aggregate.isa_sender_qualifier = cmd.isa_sender_qualifier
        if not isinstance(cmd.isa_receiver_qualifier, UnsetType):
            aggregate.isa_receiver_qualifier = cmd.isa_receiver_qualifier
        if not isinstance(cmd.gs_sender_id, UnsetType):
            aggregate.gs_sender_id = cmd.gs_sender_id
        if not isinstance(cmd.gs_receiver_id, UnsetType):
            aggregate.gs_receiver_id = cmd.gs_receiver_id
        if not isinstance(cmd.transaction_type, UnsetType):
            aggregate.transaction_type = cmd.transaction_type
        if not isinstance(cmd.default_standard, UnsetType):
            aggregate.default_standard = cmd.default_standard
        if not isinstance(cmd.default_version, UnsetType):
            aggregate.default_version = cmd.default_version
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
