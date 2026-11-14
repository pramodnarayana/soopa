"""Re-export domain context definitions for backwards compatibility."""

from webhooks.receivers.domain.context import (
    RawIngressPayloadEnvelope,
    VerifiedEndpointContext,
)

__all__ = [
    "RawIngressPayloadEnvelope",
    "VerifiedEndpointContext",
]
