from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import cast

import structlog
from seedwork.domain.types import JsonDict, JsonValue
from seedwork.events import EventEnvelope

from pubsub.domain.dtos import AckableMessage

logger = structlog.get_logger(__name__)


class DispatchKey(StrEnum):
    """Standard message payload keys used for dispatch routing."""

    JOB_NAME = "job_name"
    EVENT_TYPE = "event_type"
    ID = "id"
    SOURCE = "source"


JsonMessageHandler = Callable[[JsonDict], Awaitable[None]]
EnvelopeMessageHandler = Callable[[EventEnvelope], Awaitable[None]]
MessageHandler = JsonMessageHandler | EnvelopeMessageHandler


class MessageDispatcher:
    """
    Lightweight, centralized event/job dispatcher.
    Routes incoming SQS/broker messages to the correct handler by matching
    a specific routing key (like `job_name` or `event_type`) in the payload.
    Supports raw JsonDict, EventEnvelope, and AckableMessage transports.
    """

    def __init__(self, dispatch_key: str) -> None:
        self.dispatch_key = dispatch_key
        self._handlers: dict[str, MessageHandler] = {}

    def subscribe(self, key_value: str, handler: MessageHandler) -> None:
        self._handlers[key_value] = handler

    @staticmethod
    def _extract_payload(
        message: JsonDict | EventEnvelope | AckableMessage,
    ) -> JsonDict | EventEnvelope:
        if not isinstance(message, AckableMessage):
            return message

        raw = message.payload
        if isinstance(raw, (bytes, str)):
            try:
                loaded = json.loads(raw if isinstance(raw, str) else raw.decode("utf-8"))
                return loaded if isinstance(loaded, dict) else {"data": loaded}
            except (json.JSONDecodeError, UnicodeDecodeError):
                logger.error("dispatcher_ackable_message_malformed_json")
                return {}
        if isinstance(raw, dict):
            return raw
        return {}

    def _resolve_routing_key(self, payload_msg: JsonDict | EventEnvelope) -> JsonValue:
        if not isinstance(payload_msg, EventEnvelope):
            direct = payload_msg.get(self.dispatch_key)
            if direct:
                return direct
            nested = payload_msg.get("payload")
            if isinstance(nested, dict):
                return nested.get(self.dispatch_key, "")
            return ""

        if self.dispatch_key == DispatchKey.EVENT_TYPE.value:
            return payload_msg.event_type
        if self.dispatch_key == DispatchKey.ID.value:
            return payload_msg.id
        if self.dispatch_key == DispatchKey.SOURCE.value:
            return payload_msg.source
        return payload_msg.payload.get(self.dispatch_key, "")

    async def dispatch(self, message: JsonDict | EventEnvelope | AckableMessage) -> None:
        payload_msg = self._extract_payload(message)
        key_value = self._resolve_routing_key(payload_msg)

        handler = self._handlers.get(key_value) if isinstance(key_value, str) else None

        if handler is None:
            logger.error(
                "unknown_dispatch_key_value", key_value=key_value, dispatch_key=self.dispatch_key
            )
            raise ValueError(f"Unknown value for '{self.dispatch_key}': {key_value}")

        if isinstance(payload_msg, EventEnvelope):
            await cast(EnvelopeMessageHandler, handler)(payload_msg)
        else:
            await cast(JsonMessageHandler, handler)(payload_msg)
