import asyncio
import contextlib
from collections.abc import Callable
from typing import Any

import structlog

from identity_worker.ports.inbound.identity_event_consumer_port import (
    IdentityEventConsumerPort,
    IdentityEventMessage,
)

logger = structlog.get_logger(__name__)


class IdentityEventDispatcher:
    """
    Centralized Inbound Adapter that polls the SQS Event Listener
    and dispatches Domain Events to registered pure business Application Services.
    """

    def __init__(self, event_consumer: IdentityEventConsumerPort):
        self.event_consumer = event_consumer
        self.is_running = False
        self._task: asyncio.Task[None] | None = None

        # Route mapping: event_type -> list of async handlers
        self._handlers: dict[str, list[Callable[[IdentityEventMessage], Any]]] = {}

    def subscribe(self, event_type: str, handler: Callable[[IdentityEventMessage], Any]) -> None:
        """Register a handler for a specific domain event type."""
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append(handler)

    def start(self) -> None:
        if not self.is_running:
            self.is_running = True
            self._task = asyncio.create_task(self._run_loop())
            logger.info("identity_sqs_event_dispatcher_started")

    async def stop(self) -> None:
        self.is_running = False
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

        logger.info("identity_sqs_event_dispatcher_stopped")

    async def _run_loop(self) -> None:
        try:
            async with self.event_consumer:
                await self._poll_continuous()
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("identity_sqs_event_dispatcher_fatal_error")
        finally:
            self.is_running = False

    async def _poll_continuous(self) -> None:
        while self.is_running:
            try:
                # Process the message via the context manager which handles ack/delete automatically
                async with self.event_consumer.process_next_event() as event:
                    if not event:
                        await asyncio.sleep(0.1)
                        continue

                    await self._dispatch(event)

            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("identity_sqs_event_dispatcher_poll_loop_error")
                await asyncio.sleep(5)

    async def _dispatch(self, event: IdentityEventMessage) -> None:
        handlers = self._handlers.get(event.event_type, [])
        if not handlers:
            logger.debug("no_handlers_registered_for_event", event_type=event.event_type)
            return

        # Execute all handlers for this event sequentially or concurrently.
        # Running sequentially here to ensure if one fails, the message is not deleted.
        for handler in handlers:
            try:
                result = handler(event)
                if asyncio.iscoroutine(result) or asyncio.isfuture(result):
                    await result
            except Exception:
                handler_name = getattr(handler, "__name__", repr(handler))
                logger.exception(
                    "handler_failed_processing_event",
                    event_type=event.event_type,
                    handler_name=handler_name,
                )
                raise  # Propagate to prevent message deletion
