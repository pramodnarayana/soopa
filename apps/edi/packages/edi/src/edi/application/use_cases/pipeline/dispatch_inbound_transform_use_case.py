from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

import structlog
from seedwork.id_registry import SystemIdPrefix
from seedwork.utils import generate_deterministic_id

from edi.config.settings import AppSettings
from edi.domain.enums import EdiDirection, PipelineEventType
from edi.ports.outbound.transformer_port import TransformerPort
from edi.ports.outbound.uow import DataPlaneUnitOfWorkPort

logger = structlog.get_logger(__name__)


class DispatchInboundTransformUseCase:
    """
    Application Use Case for orchestrating inbound EDI to JSON transformation.
    """

    def __init__(
        self,
        uow_factory: Callable[[], AbstractAsyncContextManager[DataPlaneUnitOfWorkPort]],
        transformer: TransformerPort,
        settings: AppSettings,
    ) -> None:
        self.uow_factory = uow_factory
        self.transformer = transformer
        self._settings = settings

    async def execute(self, trace_id: str, idempotency_key: str | None = None) -> None:
        """Transforms an inbound X12 EDI payload to JSON."""
        logger.info("inbound_transform.started", trace_id=trace_id)

        async with self.uow_factory() as uow, uow:
            edi_msg = await uow.transactions.get_edi_message(trace_id)
            if not edi_msg:
                raise ValueError(f"No EDI message found for trace_id={trace_id}")

            if idempotency_key:
                is_new = await uow.record_idempotency(edi_msg.tenant_id, idempotency_key)
                if not is_new:
                    logger.info("inbound_transform.duplicate_skipped", trace_id=trace_id)
                    return

            if not edi_msg.edi_data:
                raise ValueError(f"No EDI data found for trace_id={trace_id}")
            standard = edi_msg.format_standard or "X12"
            transaction_type = edi_msg.transaction_type

            # 2. Dispatch to Compute Worker
            if not idempotency_key:
                raise ValueError("idempotency_key is required for strict event chaining")

            compute_key = generate_deterministic_id(
                SystemIdPrefix.IDEMPOTENCY, idempotency_key, "COMPUTE_TRANSFORMATION_COMMAND"
            )
            await uow.outbox.append_event(
                idempotency_key=compute_key,
                event_type=PipelineEventType.COMPUTE_TRANSFORMATION_COMMAND.value,
                payload={
                    "trace_id": trace_id,
                    "direction": EdiDirection.INBOUND.value,
                    "standard": standard,
                    "transaction_type": transaction_type,
                    "tenant_id": edi_msg.tenant_id,
                },
            )
            await uow.commit()

        logger.info("inbound_transform.dispatched_to_compute", trace_id=trace_id)
