import uuid

import structlog

from edi.config.settings import AppSettings
from edi.domain.direction import MessageDirection
from edi.domain.events import PipelineEventType
from edi.ports.outbound.data_plane_unit_of_work_port import DataPlaneUnitOfWorkPort
from edi.ports.outbound.transformer_port import TransformerPort

logger = structlog.get_logger(__name__)


class DispatchInboundTransformUseCase:
    """
    Application Use Case for orchestrating inbound EDI to JSON transformation.
    """

    def __init__(
        self,
        uow: DataPlaneUnitOfWorkPort,
        transformer: TransformerPort,
        settings: AppSettings,
    ) -> None:
        self.uow = uow
        self.transformer = transformer
        self._settings = settings

    async def execute(self, trace_id: str) -> None:
        """Transforms an inbound X12 EDI payload to JSON."""
        logger.info("inbound_transform.started", trace_id=trace_id)

        async with self.uow:
            edi_msg = await self.uow.repository.get_edi_message(trace_id)
            if not edi_msg:
                raise ValueError(f"No EDI message found for trace_id={trace_id}")

            if not edi_msg.edi_data:
                raise ValueError(f"No EDI data found for trace_id={trace_id}")
            standard = edi_msg.format_standard or "X12"
            transaction_type = edi_msg.transaction_type or "UNKNOWN"

            # 2. Dispatch to Compute Worker
            compute_key = str(uuid.uuid5(uuid.NAMESPACE_OID, f"{trace_id}:COMPUTE_TRANSFORM_EVENT"))
            await self.uow.outbox.append_event(
                idempotency_key=compute_key,
                event_type=PipelineEventType.COMPUTE_TRANSFORM_EVENT.value,
                payload={
                    "trace_id": trace_id,
                    "direction": MessageDirection.INBOUND.value,
                    "standard": standard,
                    "transaction_type": transaction_type,
                    "tenant_id": edi_msg.tenant_id,
                },
            )
            await self.uow.commit()

        logger.info("inbound_transform.dispatched_to_compute", trace_id=trace_id)
