"""Direct in-process handler OutboxPublisherPort / DirectBatchDispatcherPort for the PostgreSQL Pub/Sub Engine."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Sequence
from typing import cast

import structlog
from outbox.domain.constants import BatchPublishDisposition
from outbox.domain.models import BatchPublishOutcome
from outbox.ports.outbox_publisher_port import StructuredOutboxPublisherPort
from seedwork.domain.types import JsonDict
from seedwork.events import EventEnvelope

from pubsub.domain.dtos import AckableMessage, EventDispatchOutcome
from pubsub.domain.enums import ConsumerVerdict, PayloadDispatchMode
from pubsub.enums import ConsumerAction, ConsumerDecision, ConsumerOutcome
from pubsub.exceptions import ConsumerTerminalError
from pubsub.ports.consumer_manager_port import MessageHandler
from pubsub.ports.database_queue_port import DirectBatchDispatcherPort

logger = structlog.get_logger(__name__)

_ACTION_TO_DISPOSITION: dict[ConsumerAction, BatchPublishDisposition] = {
    ConsumerAction.ACK: BatchPublishDisposition.ACK,
    ConsumerAction.NACK: BatchPublishDisposition.NACK,
    ConsumerAction.DLQ: BatchPublishDisposition.DLQ,
}


class DirectHandlerOutboxPublisher(DirectBatchDispatcherPort, StructuredOutboxPublisherPort):
    """Bridges an outbox/queue drain loop (`FOR UPDATE SKIP LOCKED`) directly to a worker's `MessageHandler`.

    Uses explicit `PayloadDispatchMode` (zero runtime signature reflection) and retains zero
    in-memory event history (zero OOM risk). Preserves first-class `ACK`, `NACK(visibility_timeout_seconds)`,
    and `DLQ` dispositions.
    """

    def __init__(
        self,
        handler: MessageHandler,
        queue_name: str = "direct-outbox",
        *,
        dispatch_mode: PayloadDispatchMode = PayloadDispatchMode.JSON_DICT,
    ) -> None:
        self.handler = handler
        self.queue_name = queue_name
        self.dispatch_mode = dispatch_mode

    async def publish(self, event: EventEnvelope) -> None:
        outcomes = await self.dispatch_batch_outcomes([event])
        if not outcomes or outcomes[0].action == ConsumerAction.NACK:
            err = outcomes[0].error_message if outcomes else "Handler NACKed event"
            raise RuntimeError(
                f"Direct handler failed or NACKed outbox event {event.id} ({event.event_type}): {err}"
            )

    async def publish_batch(self, events: list[EventEnvelope]) -> list[str]:
        """OutboxPublisherPort compatibility: only ACKed events are marked PROCESSED."""
        outcomes = await self.dispatch_batch_outcomes(events)
        return [o.event_id for o in outcomes if o.action == ConsumerAction.ACK]

    async def publish_batch_structured(
        self, events: Sequence[EventEnvelope]
    ) -> list[BatchPublishOutcome]:
        """StructuredOutboxPublisherPort implementation preserving exact ACK/NACK/DLQ verdicts."""
        outcomes = await self.dispatch_batch_outcomes(events)
        return [
            BatchPublishOutcome(
                event_id=o.event_id,
                disposition=_ACTION_TO_DISPOSITION.get(o.action, BatchPublishDisposition.NACK),
                error_message=o.error_message,
                retry_delay_seconds=o.retry_delay_seconds,
            )
            for o in outcomes
        ]

    async def dispatch_batch_outcomes(
        self,
        events: Sequence[EventEnvelope],
    ) -> list[EventDispatchOutcome]:
        """Dispatches each event and returns its exact structured disposition (ACK / NACK / DLQ)."""
        outcomes: list[EventDispatchOutcome] = []
        for event in events:
            outcomes.append(await self._dispatch_single_event(event))
        return outcomes

    async def _dispatch_single_event(self, event: EventEnvelope) -> EventDispatchOutcome:
        envelope_dict: JsonDict = event.to_dict()
        explicitly_nacked = False
        nack_requeue = True
        nack_delay_seconds: int | None = None

        async def _ack() -> None:
            pass

        async def _nack(
            *, requeue: bool = True, visibility_timeout_seconds: int | None = None
        ) -> None:
            nonlocal explicitly_nacked, nack_requeue, nack_delay_seconds
            explicitly_nacked = True
            nack_requeue = requeue
            nack_delay_seconds = visibility_timeout_seconds

        try:
            if self.dispatch_mode == PayloadDispatchMode.JSON_DICT:
                handler_dict = cast(
                    Callable[[JsonDict], Awaitable[ConsumerOutcome | ConsumerVerdict | None]],
                    self.handler,
                )
                outcome = await handler_dict(envelope_dict)
            else:
                raw_bytes = json.dumps(envelope_dict).encode("utf-8")
                ackable = AckableMessage(
                    payload=raw_bytes,
                    headers={"event_type": event.event_type, "source": event.source},
                    key=event.tenant_id.encode("utf-8") if event.tenant_id else None,
                    ack=_ack,
                    nack=_nack,
                    destination_uri=f"db://{self.queue_name}",
                    message_id=event.id,
                )
                handler_msg = cast(
                    Callable[[AckableMessage], Awaitable[ConsumerOutcome | ConsumerVerdict | None]],
                    self.handler,
                )
                outcome = await handler_msg(ackable)

            if explicitly_nacked:
                action = ConsumerAction.NACK if nack_requeue else ConsumerAction.DLQ
                return EventDispatchOutcome(
                    event_id=event.id,
                    action=action,
                    error_message="Handler explicitly NACKed message",
                    retry_delay_seconds=nack_delay_seconds,
                )

            return self._translate_outcome(event.id, outcome)
        except ConsumerTerminalError as exc:
            logger.error(
                "direct_outbox_consumer_terminal_error_dead_lettered",
                queue=self.queue_name,
                event_id=event.id,
                event_type=event.event_type,
                error=str(exc),
            )
            return EventDispatchOutcome(
                event_id=event.id,
                action=ConsumerAction.DLQ,
                error_message=str(exc) or type(exc).__name__,
            )
        except Exception as exc:
            logger.exception(
                "direct_outbox_consumer_handler_failed",
                queue=self.queue_name,
                event_id=event.id,
                event_type=event.event_type,
                error=str(exc),
            )
            return EventDispatchOutcome(
                event_id=event.id,
                action=ConsumerAction.NACK,
                error_message=str(exc) or type(exc).__name__,
            )

    @staticmethod
    def _translate_outcome(
        event_id: str,
        outcome: ConsumerOutcome | ConsumerVerdict | None,
    ) -> EventDispatchOutcome:
        if outcome is None:
            return EventDispatchOutcome(event_id=event_id, action=ConsumerAction.ACK)
        if isinstance(outcome, ConsumerDecision):
            return EventDispatchOutcome(
                event_id=event_id,
                action=outcome.action,
                error_message=(
                    None
                    if outcome.action == ConsumerAction.ACK
                    else f"Handler returned {outcome.action.value}"
                ),
                retry_delay_seconds=outcome.visibility_timeout_seconds,
            )
        if isinstance(outcome, ConsumerVerdict):
            if outcome == ConsumerVerdict.ACK:
                return EventDispatchOutcome(event_id=event_id, action=ConsumerAction.ACK)
            if outcome == ConsumerVerdict.REJECT:
                return EventDispatchOutcome(
                    event_id=event_id,
                    action=ConsumerAction.DLQ,
                    error_message="Handler returned REJECT",
                )
            return EventDispatchOutcome(
                event_id=event_id,
                action=ConsumerAction.NACK,
                error_message="Handler returned NACK",
            )
        if isinstance(outcome, ConsumerAction):
            return EventDispatchOutcome(
                event_id=event_id,
                action=outcome,
                error_message=(
                    None if outcome == ConsumerAction.ACK else f"Handler returned {outcome.value}"
                ),
            )
        return EventDispatchOutcome(event_id=event_id, action=ConsumerAction.ACK)
