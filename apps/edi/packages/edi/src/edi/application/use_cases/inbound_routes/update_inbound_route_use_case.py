from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from seedwork.constants import SystemIdPrefix
from seedwork.domain.types import UNSET, UnsetType
from seedwork.utils import generate_id

from edi.domain.enums import EdiConnectionType, EdiEventType
from edi.domain.events import ProvisioningEvent
from edi.domain.models.base import ProcessingMode
from edi.ports.outbound.uow import ControlPlaneUnitOfWorkPort as ControlPlaneUnitOfWork

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class UpdateInboundRouteCmd:
    isa_sender_id: str | UnsetType = UNSET
    isa_receiver_id: str | UnsetType = UNSET
    transaction_type: str | UnsetType = UNSET
    webhook_id: str | UnsetType | None = UNSET
    as2_partner_id: str | UnsetType | None = UNSET
    sftp_partner_id: str | UnsetType | None = UNSET
    connection_type: EdiConnectionType | UnsetType | None = UNSET
    active: bool | UnsetType = UNSET
    name: str | UnsetType | None = UNSET
    trading_partner_id: str | UnsetType = UNSET
    gs_sender_id: str | UnsetType = UNSET
    gs_receiver_id: str | UnsetType = UNSET
    processing_mode: str | UnsetType = UNSET


class UpdateInboundRouteUseCase:
    def __init__(self, uow: ControlPlaneUnitOfWork) -> None:
        self.uow = uow

    async def update_inbound_route(  # noqa: C901
        self,
        tenant_id: str,
        route_id: str,
        cmd: UpdateInboundRouteCmd,
        idempotency_key: str | None = None,
    ) -> bool:
        aggregate = await self.uow.inbound_routes.get_inbound_route_by_id(tenant_id, route_id)
        if not aggregate:
            return False

        if not isinstance(cmd.isa_sender_id, UnsetType):
            aggregate.isa_sender_id = cmd.isa_sender_id
        if not isinstance(cmd.isa_receiver_id, UnsetType):
            aggregate.isa_receiver_id = cmd.isa_receiver_id
        if not isinstance(cmd.transaction_type, UnsetType):
            aggregate.transaction_type = cmd.transaction_type
        if not isinstance(cmd.webhook_id, UnsetType):
            aggregate.webhook_id = cmd.webhook_id
        if not isinstance(cmd.as2_partner_id, UnsetType):
            aggregate.as2_partner_id = cmd.as2_partner_id
        if not isinstance(cmd.sftp_partner_id, UnsetType):
            aggregate.sftp_partner_id = cmd.sftp_partner_id
        if not isinstance(cmd.connection_type, UnsetType):
            aggregate.connection_type = cmd.connection_type
        if not isinstance(cmd.active, UnsetType):
            aggregate.active = cmd.active
        if not isinstance(cmd.name, UnsetType):
            aggregate.name = cmd.name
        if not isinstance(cmd.trading_partner_id, UnsetType):
            aggregate.trading_partner_id = cmd.trading_partner_id
        if not isinstance(cmd.gs_sender_id, UnsetType):
            aggregate.gs_sender_id = cmd.gs_sender_id
        if not isinstance(cmd.gs_receiver_id, UnsetType):
            aggregate.gs_receiver_id = cmd.gs_receiver_id
        if not isinstance(cmd.processing_mode, UnsetType):
            aggregate.processing_mode = (
                ProcessingMode(cmd.processing_mode)
                if isinstance(cmd.processing_mode, str)
                else None
            )

        aggregate.updated_at = datetime.now(UTC).replace(tzinfo=None)

        aggregate.add_domain_event(
            ProvisioningEvent(
                tenant_id=tenant_id,
                event_type=EdiEventType.edi_inbound_route_updated,
                resource_id=route_id,
                idempotency_key=idempotency_key or generate_id(SystemIdPrefix.GENERIC),
            )
        )

        await self.uow.inbound_routes.save(aggregate)

        logger.info(
            "inbound_route_updated",
            route_id=route_id,
            tenant_id=tenant_id,
        )

        return True
