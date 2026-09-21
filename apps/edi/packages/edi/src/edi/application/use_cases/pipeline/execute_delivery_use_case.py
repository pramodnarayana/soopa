import contextlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass

import structlog

from edi.core.pipeline.delivery.base import BaseDeliveryStrategy, TerminalDeliveryError
from edi.domain.enums import MessageStatus
from edi.domain.events import DeliveryFailed, DeliverySuccessful, DomainEvent
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

        # 1. Fetch message and perform pre-delivery idempotency check
        async with self.uow_factory() as uow, uow:
            if idempotency_key:
                # Do a read-only check first so we don't insert until we actually succeed
                is_processed = await uow.has_been_processed(command.tenant_id, idempotency_key)
                if is_processed:
                    logger.info(
                        "delivery_worker.duplicate_deliver_skipped",
                        trace_id=command.trace_id,
                        idempotency_key=idempotency_key,
                    )
                    return

            edi_msg = await uow.transactions.get_edi_message(command.trace_id)
            if not edi_msg:
                raise ValueError(f"No EDI Message found for trace_id={command.trace_id}")

        # 2. Execute delivery outside the UOW to prevent holding DB connections during network I/O
        status = MessageStatus.DELIVERED
        domain_event: DomainEvent | None = None
        try:
            await strategy.deliver(command.trace_id, command.partner_id, edi_msg, idempotency_key)
            domain_event = DeliverySuccessful(
                trace_id=command.trace_id,
                tenant_id=command.tenant_id,
                direction=edi_msg.direction,
            )
            logger.info("delivery_worker.delivery_successful", trace_id=command.trace_id)
        except TerminalDeliveryError as e:
            status = MessageStatus.FAILED
            domain_event = DeliveryFailed(
                trace_id=command.trace_id,
                tenant_id=command.tenant_id,
                direction=edi_msg.direction,
                failure_reason=str(e),
            )
            logger.exception(
                "delivery_worker.delivery_failed",
                trace_id=command.trace_id,
                strategy=command.strategy_type,
                partner_id=command.partner_id,
            )

        # 3. Record final outcome and lock idempotency in a single transaction
        async with self.uow_factory() as uow, uow:
            if idempotency_key:
                is_new = await uow.record_idempotency(command.tenant_id, idempotency_key)
                if not is_new:
                    logger.info(
                        "delivery_worker.concurrent_duplicate_deliver_skipped",
                        trace_id=command.trace_id,
                        idempotency_key=idempotency_key,
                    )
                    return

            # Re-fetch because the object from the previous session is detached
            edi_msg = await uow.transactions.get_edi_message(command.trace_id)
            if not edi_msg:
                raise ValueError(f"No EDI Message found for trace_id={command.trace_id}")

            edi_msg.status = status
            if domain_event:
                edi_msg.add_domain_event(domain_event)

            # Save the aggregate (which flushes domain events)
            await uow.transactions.save(edi_msg)
            await uow.commit()
