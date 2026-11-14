"""Raw ingestion buffer port protocol."""

from __future__ import annotations

from typing import Protocol

from webhooks.receivers.domain.models import RawIngressPayloadEnvelope


class RawIngestionPort(Protocol):
    """Protocol for durably buffering raw inbound payloads into Kafka or an Outbox ledger."""

    async def ingest_raw_payload(self, envelope: RawIngressPayloadEnvelope) -> str:
        """Buffers the raw payload and returns an incepted trace ID or record ID."""
        ...
