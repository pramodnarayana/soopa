"""Centralized HMAC cryptographic signing utilities."""

from __future__ import annotations

import hashlib
import hmac


def sign_payload(secret: str | bytes, payload: bytes) -> str:
    """Computes a hexadecimal HMAC-SHA256 signature for a raw payload."""
    secret_bytes = secret.encode("utf-8") if isinstance(secret, str) else secret
    return hmac.new(secret_bytes, payload, hashlib.sha256).hexdigest()


def sign_timestamped_payload(
    secret: str | bytes,
    payload: bytes,
    timestamp: str | int,
) -> str:
    """Computes a Stripe/Slack-style timestamped HMAC signature.

    Envelope format:
        payload_to_sign = f"{timestamp}.".encode("utf-8") + payload
        signature = f"t={timestamp},v1={hmac_sha256}"
    """
    ts_str = str(timestamp)
    ts_payload = f"{ts_str}.".encode() + payload
    hex_digest = sign_payload(secret, ts_payload)
    return f"t={ts_str},v1={hex_digest}"
