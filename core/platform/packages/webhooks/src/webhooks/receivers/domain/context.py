"""Domain context definitions and payload envelopes for webhook ingress receivers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from webhooks.receivers.domain.enums import VerificationStrategy


@dataclass(frozen=True)
class VerifiedEndpointContext:
    """Authentication and identity context of a validated inbound webhook endpoint."""

    endpoint_id: str
    tenant_id: str
    endpoint_slug: str
    verification_strategy: VerificationStrategy
    bound_connection_id: str | None = None


@dataclass(frozen=True)
class RawIngressPayloadEnvelope:
    """Raw payload envelope captured at Layer 1 perimeter edge."""

    tenant_id: str
    endpoint_id: str
    headers: Mapping[str, str]
    raw_body: bytes
    query_params: Mapping[str, str] = field(default_factory=dict)
    trace_id: str | None = None
    correlation_id: str | None = None
