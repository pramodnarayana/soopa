"""Unit tests for cryptographic HMAC and timestamp verification routines."""

from __future__ import annotations

import time

from webhooks.crypto.hmac_signer import sign_payload, sign_timestamped_payload
from webhooks.crypto.hmac_verifier import (
    timing_safe_verify_hmac,
    timing_safe_verify_timestamped,
)
from webhooks.crypto.timestamp_validator import validate_timestamp


def test_sign_payload_and_verify_hmac() -> None:
    secret = "whsec_supersecretkey123"
    payload = b'{"event":"reading.created","value":42.5}'

    signature = sign_payload(secret, payload)
    assert len(signature) == 64
    assert timing_safe_verify_hmac(secret, payload, signature) is True
    # Test prefix stripping
    assert timing_safe_verify_hmac(secret, payload, f"sha256={signature}") is True
    # Test tamper
    tampered_payload = b'{"event":"reading.created","value":43.0}'
    assert timing_safe_verify_hmac(secret, tampered_payload, signature) is False
    assert timing_safe_verify_hmac("wrong_secret", payload, signature) is False
    assert timing_safe_verify_hmac(secret, payload, "") is False


def test_sign_timestamped_and_verify() -> None:
    secret = "whsec_test_stripe_secret"
    payload = b'{"id":"evt_12345"}'
    now = time.time()

    header = sign_timestamped_payload(secret, payload, int(now))
    assert header.startswith("t=")
    assert ",v1=" in header

    assert timing_safe_verify_timestamped(secret, payload, header, tolerance_seconds=300) is True

    # Tampered payload fails
    assert (
        timing_safe_verify_timestamped(secret, b"tampered", header, tolerance_seconds=300) is False
    )

    # Expired timestamp fails
    old_time = now - 600
    expired_header = sign_timestamped_payload(secret, payload, int(old_time))
    assert (
        timing_safe_verify_timestamped(
            secret, payload, expired_header, tolerance_seconds=300, current_time=now
        )
        is False
    )

    # Empty/malformed header fails
    assert timing_safe_verify_timestamped(secret, payload, "") is False
    assert timing_safe_verify_timestamped(secret, payload, "invalid_header_format") is False


def test_validate_timestamp() -> None:
    now = 1000.0
    assert validate_timestamp("1000", tolerance_seconds=30, current_time=now) is True
    assert validate_timestamp("1020", tolerance_seconds=30, current_time=now) is True
    assert validate_timestamp("980", tolerance_seconds=30, current_time=now) is True
    assert validate_timestamp("900", tolerance_seconds=30, current_time=now) is False
    assert validate_timestamp("invalid", tolerance_seconds=30, current_time=now) is False
