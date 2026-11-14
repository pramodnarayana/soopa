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
    Rejects malformed non-ASCII signatures before comparison.
    """
    if not signature or not signature.isascii():
        return False

    cleaned_signature = signature.strip()
    if cleaned_signature.lower().startswith("sha256="):
        cleaned_signature = cleaned_signature[7:].strip()

    if not cleaned_signature or not cleaned_signature.isascii():
        return False

    expected_signature = sign_payload(secret, payload)
    return hmac.compare_digest(
        expected_signature.encode("ascii"),
        cleaned_signature.encode("ascii"),
    )


def timing_safe_verify_timestamped(
    secret: str | bytes,
    payload: bytes,
    signature_header: str,
    tolerance_seconds: int = 300,
    current_time: float | None = None,
) -> bool:
    """Verifies Stripe/Slack-style timestamped HMAC signatures in constant time.

    Preserves multiple 'v1=' candidate signatures to support cryptographic secret rotation.
    Expected header format:
        t=1614555555,v1=sig_hash_1,v1=sig_hash_2
    """
    if not signature_header or not signature_header.isascii():
        return False

    timestamp_str: str | None = None
    v1_signatures: list[str] = []
    for item in signature_header.split(","):
        if "=" in item:
            key, val = item.strip().split("=", 1)
            k = key.strip()
            v = val.strip()
            if k == "t":
                timestamp_str = v
            elif k == "v1":
                v1_signatures.append(v)

    if not timestamp_str or not v1_signatures:
        return False

    if not validate_timestamp(timestamp_str, tolerance_seconds, current_time):
        return False

    ts_payload = f"{timestamp_str}.".encode("ascii") + payload
    expected_v1 = sign_payload(secret, ts_payload).encode("ascii")

    matched = False
    for v1_sig in v1_signatures:
        if v1_sig.isascii() and hmac.compare_digest(expected_v1, v1_sig.encode("ascii")):
            matched = True

    return matched
