import logging
import uuid

from domain.events import PipelineEventType
from domain.models import EdiMessageDomainModel

from pipeline.ports.repository import RepositoryPort
from pipeline.ports.vault import VaultPort

logger = logging.getLogger(__name__)


class BaseDeliveryStrategy:
    """Base class for delivery strategies."""

    def __init__(self, repository: RepositoryPort, vault: VaultPort | None = None) -> None:
        self.repository = repository
        self.vault = vault

    async def _emit_delivery_completed(self, trace_id: str, direction: str, status: str) -> None:
        event_key = str(uuid.uuid5(uuid.NAMESPACE_OID, f"{trace_id}:DELIVERY_COMPLETED:{status}"))
        await self.repository.publish_outbox_event(
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
