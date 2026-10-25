"""Port protocol for decoding raw inbound bytes into structured JSON/objects."""

from __future__ import annotations

from typing import Protocol

from seedwork.domain.types import JsonValue

from ip.engine.domain.exceptions import IpError, Result


class InboundPayloadDecoderPort(Protocol):
    """Protocol for content-type based body deserialization (JSON, Form-Encoded, XML)."""

    def decode(
        self,
        *,
        content_type: str,
        raw_body: bytes,
    ) -> Result[JsonValue, IpError]:
        """Parses the raw body according to the provided MIME content type."""
        ...
