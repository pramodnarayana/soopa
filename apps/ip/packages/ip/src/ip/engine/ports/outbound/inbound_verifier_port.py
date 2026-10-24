"""Port protocol for authenticating external incoming webhooks and push payloads."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from ip.engine.domain.exceptions import IpError, Result


class InboundVerifierPort(Protocol):
    """Protocol for cryptographic and credential verification of incoming push notifications."""

    def verify(
        self,
        *,
        headers: Mapping[str, str],
        raw_body: bytes,
        secret: str,
        tolerance_seconds: int = 300,
    ) -> Result[bool, IpError]:
        """Validates the incoming webhook signature or token.

        Returns Result.ok(True) on successful verification or Result.fail(InboundVerificationFailedError).
        """
        ...
