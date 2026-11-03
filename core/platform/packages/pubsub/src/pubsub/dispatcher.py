from __future__ import annotations

from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import cast

import structlog
from seedwork.domain.types import JsonDict, JsonValue
from seedwork.events import EventEnvelope

logger = structlog.get_logger(__name__)


class DispatchKey(StrEnum):
    """Standard message payload keys used for dispatch routing."""

    JOB_NAME = "job_name"
    EVENT_TYPE = "event_type"


JsonMessageHandler = Callable[[JsonDict], Awaitable[None]]
EnvelopeMessageHandler = Callable[[EventEnvelope], Awaitable[None]]
MessageHandler = JsonMessageHandler | EnvelopeMessageHandler


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
        key_value: JsonValue
        if isinstance(message, EventEnvelope):
            if self.dispatch_key == DispatchKey.EVENT_TYPE.value:
                key_value = message.event_type
            elif self.dispatch_key == "id":
                key_value = message.id
            elif self.dispatch_key == "source":
                key_value = message.source
            else:
                key_value = message.payload.get(self.dispatch_key, "")
        else:
            key_value = message.get(self.dispatch_key, "")

        handler = self._handlers.get(key_value) if isinstance(key_value, str) else None

        if handler is None:
            logger.error(
                "unknown_dispatch_key_value", key_value=key_value, dispatch_key=self.dispatch_key
            )
            raise ValueError(f"Unknown value for '{self.dispatch_key}': {key_value}")

        if isinstance(message, EventEnvelope):
            await cast(EnvelopeMessageHandler, handler)(message)
        else:
            await cast(JsonMessageHandler, handler)(message)
