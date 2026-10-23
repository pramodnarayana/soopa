"""Inbound webhook verifiers implementing InboundVerifierPort using Strategy pattern."""

from __future__ import annotations

import hmac
import time
from collections.abc import Mapping

import structlog
from ip.engine.domain.exceptions import InboundVerificationFailedError, IpError, Result
from ip.engine.ports.outbound.inbound_verifier_port import InboundVerifierPort
from security.adapters.signatures.hmac_signer import HmacSigner

logger = structlog.get_logger(__name__)


class NoOpVerifier(InboundVerifierPort):
    """Passthrough verifier that accepts any payload without checking signatures."""

    def verify(
        self,
        *,
        headers: Mapping[str, str],
        raw_body: bytes,
        secret: str,
        tolerance_seconds: int = 300,
    ) -> Result[bool, IpError]:
        return Result.ok(True)


class StaticTokenVerifier(InboundVerifierPort):
    """Verifies static secret header (e.g. X-Webhook-Token or Bearer token)."""

    def __init__(self, header_name: str = "x-webhook-token") -> None:
        self._header_name = header_name.lower()

    def verify(
        self,
        *,
        headers: Mapping[str, str],
        raw_body: bytes,
        secret: str,
        tolerance_seconds: int = 300,
    ) -> Result[bool, IpError]:
        normalized_headers = {k.lower(): v for k, v in headers.items()}
        incoming_token = normalized_headers.get(self._header_name)
        if not incoming_token:
            auth_header = normalized_headers.get("authorization", "")
            if auth_header.lower().startswith("bearer "):
                incoming_token = auth_header[7:].strip()

        if not incoming_token or not hmac.compare_digest(incoming_token, secret):
            logger.error(
                "static_token_verification_failed",
                header_name=self._header_name,
            )
            return Result.fail(
                InboundVerificationFailedError(
                    message="Missing or invalid webhook authentication token."
                )
            )
        return Result.ok(True)


class HmacSignatureVerifier(InboundVerifierPort):
    """HMAC-SHA256 signature verifier with timestamp tolerance replay protection.

    Delegates cryptographic signature calculation and constant-time verification to
    the centralized platform HmacSigner adapter.
    """

    def __init__(
        self,
        signature_header: str = "x-hub-signature-256",
        timestamp_header: str | None = "x-timestamp",
        prefix: str = "sha256=",
    ) -> None:
        self._signature_header = signature_header.lower()
        self._timestamp_header = timestamp_header.lower() if timestamp_header else None
        self._prefix = prefix

    def verify(
        self,
        *,
        headers: Mapping[str, str],
        raw_body: bytes,
        secret: str,
        tolerance_seconds: int = 300,
    ) -> Result[bool, IpError]:
        normalized = {k.lower(): v for k, v in headers.items()}
        raw_signature = normalized.get(self._signature_header)

        if not raw_signature:
            logger.error(
                "inbound_hmac_missing_signature_header",
                header=self._signature_header,
            )
            return Result.fail(
                InboundVerificationFailedError(
                    message=f"Missing signature header '{self._signature_header}'."
                )
            )

        if self._prefix and raw_signature.startswith(self._prefix):
            raw_signature = raw_signature[len(self._prefix) :]

        # 1. Timestamp validation (replay protection)
        if self._timestamp_header:
            ts_str = normalized.get(self._timestamp_header)
            if not ts_str:
                logger.error(
                    "inbound_hmac_missing_timestamp_header",
                    header=self._timestamp_header,
                )
                return Result.fail(
                    InboundVerificationFailedError(
                        message=f"Missing timestamp header '{self._timestamp_header}'."
                    )
                )
            try:
                ts = float(ts_str)
                now = time.time()
                if abs(now - ts) > tolerance_seconds:
                    logger.error(
                        "inbound_hmac_timestamp_out_of_tolerance",
                        timestamp=ts,
                        now=now,
                        tolerance=tolerance_seconds,
                    )
                    return Result.fail(
                        InboundVerificationFailedError(
                            message=f"Webhook timestamp {ts} exceeds tolerance of {tolerance_seconds}s."
                        )
                    )
            except ValueError:
                logger.error(
                    "inbound_hmac_invalid_timestamp_format",
                    timestamp_header=self._timestamp_header,
                )
                return Result.fail(
                    InboundVerificationFailedError(
                        message=f"Invalid timestamp header format: '{ts_str}'."
                    )
                )

        # 2. Cryptographic signature verification via platform HmacSigner
        if not secret or not secret.strip():
            logger.error("inbound_hmac_empty_secret")
            return Result.fail(
                InboundVerificationFailedError(message="Webhook secret is not configured or empty.")
            )

        payload_to_verify = (
            f"{ts_str}.".encode() + raw_body if (self._timestamp_header and ts_str) else raw_body
        )
        signer = HmacSigner(secret)
        if not signer.verify(payload_to_verify, raw_signature):
            logger.error(
                "inbound_hmac_signature_mismatch",
                header=self._signature_header,
            )
            return Result.fail(
                InboundVerificationFailedError(
                    message="Cryptographic signature verification failed."
                )
            )

        return Result.ok(True)
