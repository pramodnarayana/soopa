"""Centralized timing-safe HMAC cryptographic verification utilities."""

from __future__ import annotations

import hmac

from webhooks.crypto.hmac_signer import sign_payload
from webhooks.crypto.timestamp_validator import validate_timestamp


def timing_safe_verify_hmac(
    secret: str | bytes,
    payload: bytes,
    signature: str,
) -> bool:
    """Performs constant-time HMAC-SHA256 signature verification.

    Strips optional prefixes like 'sha256=' to support GitHub/Shopify conventions.
    """
    if not signature:
        return False

    cleaned_signature = signature.strip()
    if cleaned_signature.lower().startswith("sha256="):
        cleaned_signature = cleaned_signature[7:].strip()

    expected_signature = sign_payload(secret, payload)
    return hmac.compare_digest(expected_signature, cleaned_signature)


def timing_safe_verify_timestamped(
    secret: str | bytes,
    payload: bytes,
    signature_header: str,
    tolerance_seconds: int = 300,
    current_time: float | None = None,
) -> bool:
    """Verifies Stripe/Slack-style timestamped HMAC signatures in constant time.

    Expected header format:
        t=1614555555,v1=5257a869e7ecebeda32affa62cdca3fa51cad7e77a0e56ff536d0ce8e108d8bd
    """
    if not signature_header:
        return False

    parts: dict[str, str] = {}
    for item in signature_header.split(","):
        if "=" in item:
            key, val = item.strip().split("=", 1)
            parts[key.strip()] = val.strip()

    timestamp_str = parts.get("t")
    v1_sig = parts.get("v1")

    if not timestamp_str or not v1_sig:
        return False

    if not validate_timestamp(timestamp_str, tolerance_seconds, current_time):
        return False

    ts_payload = f"{timestamp_str}.".encode() + payload
    expected_v1 = sign_payload(secret, ts_payload)
    return hmac.compare_digest(expected_v1, v1_sig)
