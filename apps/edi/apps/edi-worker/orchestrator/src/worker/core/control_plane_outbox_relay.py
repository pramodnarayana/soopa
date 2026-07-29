import logging

from database.connection import DatabaseRouter
from database.models.control_plane import ControlPlaneOutbox
from domain.events import ProvisioningEvent, ProvisioningEventType
from sqlalchemy import select

from worker.ports.message_publisher import MessagePublisherPort, PublishMessageEnvelope

logger = logging.getLogger(__name__)

_BATCH_SIZE = 100


def _build_provision_event(outbox_row: ControlPlaneOutbox) -> ProvisioningEvent:
    """
    Constructs a typed ProvisioningEvent from an outbox row.

    The outbox stores event_type and tenant_id as first-class columns;
    the payload carries the resource-specific data (e.g. resource_id).
    This function is the single, explicit translation point between the
    persistence representation and the domain event contract.
    """
    return ProvisioningEvent(
        tenant_id=outbox_row.tenant_id,
        event_type=ProvisioningEventType(outbox_row.event_type),
        resource_id=outbox_row.payload.get("resource_id") if outbox_row.payload else None,
    )


class ControlPlaneOutboxRelayService:
    _PROVISIONING_QUEUE = "edi-tenant-sync.fifo"

    def __init__(
        self,
        db_router: DatabaseRouter,
        message_publisher: MessagePublisherPort,
        queue_name: str | None = None,
    ) -> None:
        self.db_router = db_router
        self.message_publisher = message_publisher
        self._queue_name = queue_name or self._PROVISIONING_QUEUE

    async def relay_pending_events(self) -> int:
        """
        Sweeps the global control-plane outbox for PENDING provisioning events
        and forwards each one to the SQS queue using concurrent batching.
        """
        logger.debug("[ControlPlaneOutboxRelay] Running sweep")

        total_processed = 0

        async with self.message_publisher.connect():
            try:
                processed = await self._sweep_global()
                total_processed += processed
            except Exception as e:
                logger.error(f"[ControlPlaneOutboxRelay] Failed sweeping global outbox: {e}")

        if total_processed > 0:
            logger.info(
                f"[ControlPlaneOutboxRelay] Sweep complete. Total events forwarded: {total_processed}"
            )

        return total_processed

    async def _sweep_global(self) -> int:
        processed = 0
        async for session in self.db_router.get_global_session():
            stmt = (
                select(ControlPlaneOutbox)
                .where(ControlPlaneOutbox.status == "PENDING")
                .limit(_BATCH_SIZE)
                .with_for_update(skip_locked=True)
            )
            result = await session.execute(stmt)
            events = result.scalars().all()

            if not events:
                logger.debug("[ControlPlaneOutboxRelay] No pending events in global outbox")
                return 0

            # Provisioning queue for control plane events
            queue_name = self._queue_name
            messages = []
            for event in events:
                provision_event = _build_provision_event(event)
                messages.append(
                    PublishMessageEnvelope(
                        message_id=str(event.id),
                        event_type=event.event_type,
                        event=provision_event.model_dump(mode="json"),
                        idempotency_key=str(event.idempotency_key)
                        if event.idempotency_key
                        else str(event.id),
                        partition_key=event.tenant_id,
                    )
                )

            successful_ids = await self.message_publisher.publish_batch(queue_name, messages)

            for event in events:
                if str(event.id) in successful_ids:
                    event.status = "PROCESSED"
                    processed += 1
                else:
                    logger.error(
                        f"[ControlPlaneOutboxRelay] Failed to forward global event id={event.id} to {queue_name}"
                    )

            await session.commit()

        return processed
