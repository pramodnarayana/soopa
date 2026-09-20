import contextlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass

import structlog
from seedwork.id_registry import SystemIdPrefix
from seedwork.utils import generate_deterministic_id

from edi.core.pipeline.delivery.base import BaseDeliveryStrategy
from edi.domain.enums import PipelineEventType
from edi.ports.outbound.uow import DataPlaneUnitOfWorkPort

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class ExecuteDeliveryCommand:
    trace_id: str
    tenant_id: str
    partner_id: str
    strategy_type: str


class ExecuteDeliveryUseCase:
    """
    Executes the final-mile EDI delivery based on the commanded strategy.
    Runs exclusively in the edi-delivery-worker.
    """

    def __init__(
        self,
        uow_factory: Callable[[], contextlib.AbstractAsyncContextManager[DataPlaneUnitOfWorkPort]],
        strategies: Mapping[str, BaseDeliveryStrategy],
    ) -> None:
        self.uow_factory = uow_factory
        self.strategies = strategies

    async def execute(
        self, command: ExecuteDeliveryCommand, idempotency_key: str | None = None
    ) -> None:
        logger.info(
            "delivery_worker.executing_delivery",
            trace_id=command.trace_id,
            strategy_type=command.strategy_type,
            partner_id=command.partner_id,
        )

        strategy = self.strategies.get(command.strategy_type)
        if not strategy:
            raise ValueError(f"Unknown delivery strategy_type: {command.strategy_type}")

        async with self.uow_factory() as uow, uow:
            edi_msg = await uow.transactions.get_edi_message(command.trace_id)
            if not edi_msg:
                raise ValueError(f"No EDI Message found for trace_id={command.trace_id}")

        try:
            await strategy.deliver(command.trace_id, command.partner_id, edi_msg, idempotency_key)
            logger.info("delivery_worker.delivery_successful", trace_id=command.trace_id)

            # Emit DELIVERY_COMPLETED domain event back to orchestrator
            completion_key = generate_deterministic_id(
                SystemIdPrefix.IDEMPOTENCY, command.trace_id, "DELIVERY_COMPLETED"
            )

            async with self.uow_factory() as uow, uow:
                await uow.outbox.append_event(
                    idempotency_key=completion_key,
                    event_type=PipelineEventType.DELIVERY_COMPLETED.value,
                    payload={
                        "trace_id": command.trace_id,
                        "tenant_id": command.tenant_id,
                    },
                )

        except Exception:
            logger.exception(
                "delivery_worker.delivery_failed",
                trace_id=command.trace_id,
                strategy=command.strategy_type,
                partner_id=command.partner_id,
            )
            raise
