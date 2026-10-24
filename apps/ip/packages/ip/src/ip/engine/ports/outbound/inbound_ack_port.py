"""Port protocol and DTOs for acknowledging external push webhooks."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol

from seedwork.domain.types import JsonDict, JsonValue


@dataclass(frozen=True)
class AckResponseDTO:
    """HTTP response representation returned to acknowledge external push notification."""

    status_code: int = 202
    headers: Mapping[str, str] = field(default_factory=dict)
    body: str | bytes | JsonDict = field(default_factory=dict)


class InboundAckPort(Protocol):
    """Protocol for formatting provider-compliant HTTP acknowledgment responses."""

    def build_ack(
        self,
        *,
        app_id: str,
        payload: JsonValue,
        headers: Mapping[str, str],
    ) -> AckResponseDTO:
        """Constructs an acknowledgment response (e.g. 202 Accepted, SOAP <Ack>, or token echo)."""
        ...
