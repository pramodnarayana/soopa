"""Lane-aware EventTypeOutboxRouter implementing OutboxPublisherPort."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from contextlib import AbstractAsyncContextManager, AsyncExitStack
from types import TracebackType
from typing import Protocol, Self, runtime_checkable

import structlog
from outbox.ports.outbox_publisher_port import OutboxPublisherPort
from seedwork.events import EventEnvelope, EventProcessingLane

logger = structlog.get_logger(__name__)

RouteKey = tuple[str, EventProcessingLane] | str


@runtime_checkable
class AsyncContextPublisherProtocol(
    OutboxPublisherPort,
    AbstractAsyncContextManager[OutboxPublisherPort],
    Protocol,
):
    """Structural protocol for OutboxPublisherPort implementations supporting async context management."""


class EventTypeOutboxRouter(OutboxPublisherPort):
    """
    Polymorphic OutboxPublisherPort composite that routes EventEnvelopes by
    `(envelope.event_type, envelope.lane)` to target publishers (e.g., realtime vs bulk SQS queues).
    """

    def __init__(
        self,
        routes: Mapping[RouteKey, OutboxPublisherPort],
        *,
        default_publisher: OutboxPublisherPort | None = None,
    ) -> None:
        self._routes: dict[RouteKey, OutboxPublisherPort] = dict(routes)
        self._default_publisher = default_publisher
        self._exit_stack: AsyncExitStack | None = None

    async def __aenter__(self) -> Self:
        self._exit_stack = AsyncExitStack()
        await self._exit_stack.__aenter__()
        unique_publishers: list[OutboxPublisherPort] = []
        for pub in self._routes.values():
            if pub not in unique_publishers:
                unique_publishers.append(pub)
        if self._default_publisher is not None and self._default_publisher not in unique_publishers:
            unique_publishers.append(self._default_publisher)

        for pub in unique_publishers:
            if isinstance(pub, AsyncContextPublisherProtocol):
                await self._exit_stack.enter_async_context(pub)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if self._exit_stack is not None:
            await self._exit_stack.__aexit__(exc_type, exc_val, exc_tb)
            self._exit_stack = None

    def resolve_publisher(self, event: EventEnvelope) -> OutboxPublisherPort | None:
        """Resolves the target OutboxPublisherPort for `(event.event_type, event.lane)`."""
        exact = self._routes.get((event.event_type, event.lane))
        if exact is not None:
            return exact
        by_type = self._routes.get(event.event_type)
        if by_type is not None:
            return by_type
        # Fallback to REALTIME lane if BULK lane shares the same queue for this event_type
        fallback_rt = self._routes.get((event.event_type, EventProcessingLane.REALTIME))
        if fallback_rt is not None:
            return fallback_rt
        return self._default_publisher

    async def publish(self, event: EventEnvelope) -> None:
        publisher = self.resolve_publisher(event)
        if publisher is None:
            logger.error(
                "outbox_router_unmapped_event_type",
                event_id=event.id,
                event_type=event.event_type,
                lane=event.lane.value,
            )
            raise ValueError(
                f"No OutboxPublisherPort configured for event_type='{event.event_type}', lane='{event.lane.value}'"
            )
        await publisher.publish(event)

    def _group_by_publisher(
        self, events: list[EventEnvelope]
    ) -> list[tuple[OutboxPublisherPort, list[EventEnvelope]]]:
        grouped: dict[int, tuple[OutboxPublisherPort, list[EventEnvelope]]] = {}
        for event in events:
            publisher = self.resolve_publisher(event)
            if publisher is None:
                logger.error(
                    "outbox_router_unmapped_event_in_batch",
                    event_id=event.id,
                    event_type=event.event_type,
                    lane=event.lane.value,
                )
                continue
            pub_id = id(publisher)
            if pub_id not in grouped:
                grouped[pub_id] = (publisher, [])
            grouped[pub_id][1].append(event)
        return list(grouped.values())

    @staticmethod
    async def _publish_group(
        publisher: OutboxPublisherPort, group_events: list[EventEnvelope]
    ) -> tuple[list[str], Exception | None]:
        try:
            acked = await publisher.publish_batch(group_events)
            return acked, None
        except Exception as exc:
            logger.exception(
                "outbox_router_group_publish_failed",
                count=len(group_events),
            )
            return [], exc

    async def publish_batch(self, events: list[EventEnvelope]) -> list[str]:
        if not events:
            return []

        groups = self._group_by_publisher(events)
        if not groups:
            return []

        results = await asyncio.gather(*[self._publish_group(pub, grp) for pub, grp in groups])

        successful_ids: list[str] = []
        first_error: Exception | None = None
        for acked, err in results:
            successful_ids.extend(acked)
            if err is not None and first_error is None:
                first_error = err

        if not successful_ids and first_error is not None:
            raise first_error

        return successful_ids


__all__ = ["EventTypeOutboxRouter", "RouteKey"]
