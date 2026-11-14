"""Timing-safe inbound cryptographic verification implementation."""

from __future__ import annotations

import hmac
from collections.abc import Mapping

from webhooks.crypto.hmac_verifier import (
    timing_safe_verify_hmac,
    timing_safe_verify_timestamped,
)
from webhooks.receivers.domain.enums import VerificationStrategy
from webhooks.receivers.ports.inbound_verifier_port import InboundVerifierPort

HEADER_TOKEN_CANDIDATES: tuple[str, ...] = (
    "x-webhook-token",
    "x-webhook-secret",
    "x-api-key",
    "x-secret",
)

HMAC_HEADER_CANDIDATES: tuple[str, ...] = (
    "x-signature-256",
    "x-hub-signature-256",
    "x-signature",
    "stripe-signature",
)

QUERY_TOKEN_CANDIDATES: tuple[str, ...] = (
    "token",
    "secret",
    "key",
    "api_key",
)


def _safe_compare(candidate: str, secret: str) -> bool:
    """Performs constant-time string comparison using ASCII byte representation.

    Rejects empty or non-ASCII candidate strings safely.
    """
    if not candidate or not secret or not candidate.isascii() or not secret.isascii():
        return False
    return hmac.compare_digest(candidate.encode("ascii"), secret.encode("ascii"))


class TimingSafeInboundVerifier(InboundVerifierPort):
    """Production implementation of InboundVerifierPort using timing-safe comparisons."""

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
        if strategy == VerificationStrategy.PUBLIC_UNAUTHENTICATED:
            return True

        secrets = [s for s in (primary_secret, secondary_secret) if s]
        if not secrets:
            return False

        normalized_headers = {k.strip().lower(): str(v).strip() for k, v in headers.items()}
        normalized_query = {k.strip().lower(): str(v).strip() for k, v in query_params.items()}

        if strategy == VerificationStrategy.SHARED_HEADER_SECRET:
            return self._verify_header_token(normalized_headers, secrets)

        if strategy == VerificationStrategy.BEARER_TOKEN:
            return self._verify_bearer_token(normalized_headers, secrets)

        if strategy == VerificationStrategy.QUERY_TOKEN:
            return self._verify_query_token(normalized_query, secrets)

        if strategy == VerificationStrategy.HMAC_SHA256:
            return self._verify_hmac_sha256(normalized_headers, raw_body, secrets)

        if strategy == VerificationStrategy.MUTUAL_TLS:
            return self._verify_mtls(normalized_headers, secrets)

        return False

    def _verify_header_token(
        self, normalized_headers: Mapping[str, str], secrets: list[str]
    ) -> bool:
        for header_name in HEADER_TOKEN_CANDIDATES:
            if candidate := normalized_headers.get(header_name):
                for secret in secrets:
                    if _safe_compare(candidate, secret):
                        return True
        return False

    def _verify_bearer_token(
        self, normalized_headers: Mapping[str, str], secrets: list[str]
    ) -> bool:
        auth_header = normalized_headers.get("authorization", "")
        if not auth_header:
            return False

        parts = auth_header.split(" ", 1)
        if len(parts) != 2 or parts[0].lower() != "bearer":
            return False

        token = parts[1].strip()
        return any(_safe_compare(token, secret) for secret in secrets)

    def _verify_query_token(self, normalized_query: Mapping[str, str], secrets: list[str]) -> bool:
        for param_name in QUERY_TOKEN_CANDIDATES:
            if candidate := normalized_query.get(param_name):
                for secret in secrets:
                    if _safe_compare(candidate, secret):
                        return True
        return False

    def _verify_hmac_sha256(
        self,
        normalized_headers: Mapping[str, str],
        raw_body: bytes,
        secrets: list[str],
    ) -> bool:
        for header_name in HMAC_HEADER_CANDIDATES:
            if sig := normalized_headers.get(header_name):
                for secret in secrets:
                    if header_name == "stripe-signature":
                        if timing_safe_verify_timestamped(secret, raw_body, sig):
                            return True
                    elif timing_safe_verify_hmac(secret, raw_body, sig):
                        return True
        return False

    def _verify_mtls(
        self,
        normalized_headers: Mapping[str, str],
        secrets: list[str] | None = None,
    ) -> bool:
        # Standard reverse proxy mTLS header convention (e.g. Envoy, NGINX, AWS ALB)
        client_verify = normalized_headers.get("x-ssl-client-verify", "")
        if client_verify.upper() not in ("SUCCESS", "OK", "TRUE"):
            return False

        # If certificate fingerprint is pinned in secrets, verify match
        active_secrets = [s for s in (secrets or []) if s and s != "not_used"]
        if active_secrets:
            client_sha = normalized_headers.get("x-ssl-client-sha256", "").strip().lower()
            if not client_sha:
                return False
            return any(_safe_compare(client_sha, s.strip().lower()) for s in active_secrets)

        # Verified transport origin context must be present
        return bool(
            normalized_headers.get("x-ssl-client-sha256")
            or normalized_headers.get("x-ssl-client-s-dn")
            or normalized_headers.get("x-ssl-client-cert")
        )
