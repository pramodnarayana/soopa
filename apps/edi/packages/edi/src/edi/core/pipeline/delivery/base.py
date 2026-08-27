import uuid
from secrets.ports.secret_store_port import SecretStorePort

import structlog

from edi.domain.events import PipelineEventType
from edi.domain.models import EdiMessageDomainModel
from edi.ports.outbound.data_plane_unit_of_work_port import DataPlaneUnitOfWorkPort

logger = structlog.get_logger(__name__)


class BaseDeliveryStrategy:
    """Base class for delivery strategies."""

    def __init__(self, uow: DataPlaneUnitOfWorkPort, vault: SecretStorePort | None = None) -> None:
        self.uow = uow
        self.secret_store = vault

    async def _emit_delivery_completed(self, trace_id: str, direction: str, status: str) -> None:
        event_key = str(uuid.uuid5(uuid.NAMESPACE_OID, f"{trace_id}:DELIVERY_COMPLETED:{status}"))
        await self.uow.outbox.append_event(
            idempotency_key=event_key,
            event_type=PipelineEventType.DELIVERY_COMPLETED,
            payload={
                "trace_id": trace_id,
                "direction": direction,
                "status": status,
            },
        )

    async def deliver(
        self,
        trace_id: str,
        partner_id: str,
        edi_msg: EdiMessageDomainModel,
        idempotency_key: str | None = None,
    ) -> None:
        raise NotImplementedError
