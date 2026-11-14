"""Inbound cryptographic verification port protocol."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from webhooks.receivers.domain.enums import VerificationStrategy


class InboundVerifierPort(Protocol):
    """Protocol for verifying inbound webhook authentication across diverse strategies."""

    def verify(
        self,
        *,
        strategy: VerificationStrategy,
        headers: Mapping[str, str],
        query_params: Mapping[str, str],
        raw_body: bytes,
        primary_secret: str,
        secondary_secret: str | None = None,
    ) -> bool:
        """Verifies incoming request against provided secret(s). Returns True if valid, False otherwise."""
        ...
