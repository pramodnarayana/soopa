import structlog
from secret_store.ports.secret_store_port import SecretStorePort
from seedwork.constants import SystemIdPrefix
from seedwork.utils import generate_deterministic_id

from edi.domain.enums import PipelineEventType
from edi.domain.models.transactions import EdiMessageDomainModel
from edi.ports.outbound.uow import DataPlaneUnitOfWorkPort

logger = structlog.get_logger(__name__)


class BaseDeliveryStrategy:
    """Base class for delivery strategies."""

    def __init__(self, uow: DataPlaneUnitOfWorkPort, vault: SecretStorePort | None = None) -> None:
        self.uow = uow
        self.secret_store = vault

    async def _emit_delivery_completed(self, trace_id: str, direction: str, status: str) -> None:
        event_key = generate_deterministic_id(
            SystemIdPrefix.IDEMPOTENCY, trace_id, f"DELIVERY_COMPLETED:{status}"
        )
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
