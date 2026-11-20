"""Port for persisting Stage-1 notification envelopes into the local outbox."""

from __future__ import annotations

from typing import Protocol

from seedwork.events import EventEnvelope


class NotificationOutboxPort(Protocol):
    """Port for persisting Stage-1 `notification.requested` EventEnvelopes into the local outbox."""

    async def publish_envelope(self, envelope: EventEnvelope) -> None: ...
