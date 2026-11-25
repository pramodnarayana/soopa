"""Universal Pub/Sub DTOs and Protocols (core/platform/packages/pubsub)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

from seedwork.domain.types import JsonDict

from pubsub.enums import ConsumerAction


class NackCallbackPort(Protocol):
    """Protocol for broker negative-acknowledgment with optional redelivery delay."""

    async def __call__(
        self,
        *,
        requeue: bool = True,
        visibility_timeout_seconds: int | None = None,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class PublishResultDTO:
    """Outcome of writing an event/message to any broker."""

    destination_uri: str
    message_id: str
    partition: int | None = None
    offset: int | None = None
    timestamp_utc: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, slots=True)
class TopicSubscriptionSpec:
    """Declarative consumer-side subscription to a logical pub/sub topic."""

    topic_name: str
    event_types: tuple[str, ...] | None = None


@dataclass(frozen=True, slots=True)
class EventDispatchOutcome:
    """First-class per-event consumer disposition returned by DirectBatchDispatcherPort."""

    event_id: str
    action: ConsumerAction
    error_message: str | None = None
    retry_delay_seconds: int | None = None


@dataclass(frozen=True, slots=True)
class AckableMessage:
    """Standardized broker-agnostic delivery envelope delivered to handlers."""

    payload: bytes | JsonDict
    ack: Callable[[], Awaitable[None]]
    nack: NackCallbackPort
    headers: Mapping[str, str] = field(default_factory=dict)
    key: bytes | None = None
    destination_uri: str = ""
    message_id: str = ""
    partition: int | None = None
    offset: int | None = None
