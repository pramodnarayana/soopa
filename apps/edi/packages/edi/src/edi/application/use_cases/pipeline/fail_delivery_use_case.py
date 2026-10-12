import contextlib
from collections.abc import Callable
from dataclasses import dataclass

import structlog
from outbox.ports.outbox_publisher_port import OutboxPublisherPort

from edi.domain.enums import MessageStatus
from edi.domain.events import DeliveryFailed
from edi.ports.outbound.uow import DataPlaneUnitOfWorkPort

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class FailDeliveryCommand:
    trace_id: str
    tenant_id: str
    reason: str


class FailDeliveryUseCase:
    """
    Use case invoked by the DLQ consumer to durably record that an EDI delivery
    has permanently failed after exhausting all retry attempts.
    """

    def __init__(
        self,
        uow_factory: Callable[[], contextlib.AbstractAsyncContextManager[DataPlaneUnitOfWorkPort]],
        publisher: OutboxPublisherPort,
    ) -> None:
        self.uow_factory = uow_factory
        self.publisher = publisher

    async def execute(self, command: FailDeliveryCommand) -> None:
        bound_logger = logger.bind(
            tenant_id=command.tenant_id,
            trace_id=command.trace_id,
            reason=command.reason,
        )

        async with self.uow_factory() as uow, uow:
            edi_msg = await uow.transactions.get_edi_message(command.trace_id)
            if not edi_msg:
                bound_logger.error("fail_delivery.edi_message_not_found")
                return

            if edi_msg.tenant_id != command.tenant_id:
                bound_logger.error("fail_delivery.tenant_mismatch")
                return

            # Skip if already in a terminal failed state to ensure idempotency
            if edi_msg.status == MessageStatus.FAILED:
                bound_logger.info("fail_delivery.already_failed")
                return

            bound_logger.info("fail_delivery.updating_state")

            # Update the domain model (status, status_message, and appends trace event)
            edi_msg.mark_delivery_failed(reason=command.reason)

            # Drop an event into the outbox for notifications
            domain_event = DeliveryFailed(
                trace_id=command.trace_id,
                tenant_id=command.tenant_id,
                direction=edi_msg.direction.value if edi_msg.direction else "OUTBOUND",
                failure_reason=command.reason,
                error_code=edi_msg.error_code,
                error_details=edi_msg.error_details,
            )
            edi_msg.add_domain_event(domain_event)

            # Save changes
            await uow.transactions.update_edi_message_status(
                trace_id=command.trace_id,
                status=edi_msg.status.value,
            )
            await uow.transactions.update_outbound_delivery_metadata(edi_msg)

            # Persist trace events and outbox domain events
            envelopes = await uow.transactions.flush_events(edi_msg)
            await uow.commit()

        try:
            for env in envelopes:
                await self.publisher.publish(env)
            bound_logger.info("fail_delivery.success")
        except Exception as e:
            bound_logger.exception("sync_dispatch_failed_falling_back_to_sweeper", error=str(e))
