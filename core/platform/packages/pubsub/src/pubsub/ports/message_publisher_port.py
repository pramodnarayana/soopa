"""Universal message publisher port protocol (core/platform/packages/pubsub/ports)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol

from seedwork.domain.exceptions import Result
from seedwork.events import EventEnvelope

from pubsub.domain.dtos import PublishResultDTO


class MessagePublisherPort(Protocol):
    """Universal outbound port for publishing raw bytes or EventEnvelopes to any broker."""

    async def publish(
        self,
        destination_uri: str,
        message: bytes | EventEnvelope,
        key: bytes | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Result[PublishResultDTO, Exception]:
        """Publishes a single message to the destination URI."""
        ...

    async def publish_batch(
        self,
        destination_uri: str,
        messages: Sequence[bytes | EventEnvelope],
        keys: Sequence[bytes | None] | None = None,
        headers: Sequence[Mapping[str, str] | None] | None = None,
    ) -> Result[tuple[PublishResultDTO, ...], Exception]:
        """Publishes a batch of messages to the destination URI."""
        ...
