from __future__ import annotations

from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from seedwork.domain.types import JsonDict
    from seedwork.events import EventEnvelope

import structlog

logger = structlog.get_logger(__name__)


class DispatchKey(StrEnum):
    """Standard message payload keys used for dispatch routing."""

    JOB_NAME = "job_name"
    EVENT_TYPE = "event_type"


# Type alias for a simple async handler that accepts either a raw message dict or an EventEnvelope.
MessageHandler = Callable[[dict[str, Any] | Any], Awaitable[None]]


class MessageDispatcher:
    """
    Lightweight, centralized event/job dispatcher.
    Routes incoming SQS messages to the correct handler by matching
    a specific routing key (like `job_name` or `event_type`) in the payload.
    """

    def __init__(self, dispatch_key: str) -> None:
        self.dispatch_key = dispatch_key
        self._handlers: dict[str, MessageHandler] = {}

    def subscribe(self, key_value: str, handler: MessageHandler) -> None:
        self._handlers[key_value] = handler

    async def dispatch(self, message: JsonDict | EventEnvelope) -> None:
        if hasattr(message, "payload"):
            key_value = getattr(message, self.dispatch_key, None)
            if key_value is None:
                key_value = message.payload.get(self.dispatch_key, "")
        else:
            key_value = message.get(self.dispatch_key, "")

        handler = self._handlers.get(key_value) if isinstance(key_value, str) else None

        if handler is None:
            logger.error(
                "unknown_dispatch_key_value", key_value=key_value, dispatch_key=self.dispatch_key
            )
            raise ValueError(f"Unknown value for '{self.dispatch_key}': {key_value}")

        await handler(message)
