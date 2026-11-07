"""Port contract for network egress security, SSRF validation, and target pinning."""

from __future__ import annotations

from typing import Protocol

from ip.engine.domain.exceptions import EndpointSecurityViolationError, Result


class EgressPolicyPort(Protocol):
    """Outbound port validating that destination URLs adhere to egress security policies."""

    def validate_url(self, url: str) -> Result[None, EndpointSecurityViolationError]:
        """Validates that destination URL is allowed and does not resolve to restricted IP ranges."""
        ...
