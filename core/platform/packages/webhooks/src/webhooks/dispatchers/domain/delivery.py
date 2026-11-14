"""Domain value objects and commands for outbound webhook delivery."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from seedwork.domain.types import JsonDict, JsonValue


class WebhookDeliveryFailureType(StrEnum):
    """Categorized failure type distinguishing transport and security errors from completed HTTP responses."""

    HTTP_ERROR = "HTTP_ERROR"
    SSRF = "SSRF"
    TIMEOUT = "TIMEOUT"
    NETWORK_ERROR = "NETWORK_ERROR"


@dataclass(frozen=True)
class WebhookDispatchCommand:
    """Command to dispatch an outbound webhook to an external URL."""

    tenant_id: str
    subscription_id: str
    url: str
    payload: bytes | JsonDict | JsonValue
    event_type: str = ""
    secret: str | None = None
    auth_token: str | None = None
    idempotency_key: str | None = None
    headers: Mapping[str, str] = field(default_factory=dict)
    timeout_seconds: float = 30.0
    allow_private_ips: bool = False

    @property
    def payload_bytes(self) -> bytes:
        """Returns the payload serialized to bytes."""
        if isinstance(self.payload, bytes):
            return self.payload
        return json.dumps(self.payload).encode("utf-8")


@dataclass(frozen=True)
class WebhookDeliveryResult:
    """Result of an outbound webhook delivery execution."""

    status_code: int
    response_body: str
    is_success: bool
    error_message: str | None = None
    failure_type: WebhookDeliveryFailureType | None = None
