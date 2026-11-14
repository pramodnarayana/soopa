"""Unit tests for timing-safe inbound verification guards."""

from __future__ import annotations

from webhooks.crypto.hmac_signer import sign_payload
from webhooks.receivers.domain.enums import VerificationStrategy
from webhooks.receivers.guards.crypto_verifier import TimingSafeInboundVerifier


def test_public_unauthenticated_strategy() -> None:
    verifier = TimingSafeInboundVerifier()
    assert (
        verifier.verify(
            strategy=VerificationStrategy.PUBLIC_UNAUTHENTICATED,
            headers={},
            query_params={},
            raw_body=b"",
            primary_secret="",
        )
        is True
    )


def test_shared_header_secret_strategy() -> None:
    verifier = TimingSafeInboundVerifier()
    primary = "whsec_primary_token_abc"
    secondary = "whsec_secondary_rotated_xyz"

    # Valid with primary secret
    headers = {"X-Webhook-Token": primary}
    assert (
        verifier.verify(
            strategy=VerificationStrategy.SHARED_HEADER_SECRET,
            headers=headers,
            query_params={},
            raw_body=b"payload",
            primary_secret=primary,
            secondary_secret=secondary,
        )
        is True
    )

    # Valid with rotated secondary secret
    headers_sec = {"X-Webhook-Token": secondary}
    assert (
        verifier.verify(
            strategy=VerificationStrategy.SHARED_HEADER_SECRET,
            headers=headers_sec,
            query_params={},
            raw_body=b"payload",
            primary_secret=primary,
            secondary_secret=secondary,
        )
        is True
    )

    # Alternate header name (X-Api-Key)
    headers_alt = {"X-Api-Key": primary}
    assert (
        verifier.verify(
            strategy=VerificationStrategy.SHARED_HEADER_SECRET,
            headers=headers_alt,
            query_params={},
            raw_body=b"payload",
            primary_secret=primary,
        )
        is True
    )

    # Invalid secret
    assert (
        verifier.verify(
            strategy=VerificationStrategy.SHARED_HEADER_SECRET,
            headers={"X-Webhook-Token": "wrong"},
            query_params={},
            raw_body=b"payload",
            primary_secret=primary,
        )
        is False
    )


def test_bearer_token_strategy() -> None:
    verifier = TimingSafeInboundVerifier()
    secret = "my_bearer_token_999"

    assert (
        verifier.verify(
            strategy=VerificationStrategy.BEARER_TOKEN,
            headers={"Authorization": f"Bearer {secret}"},
            query_params={},
            raw_body=b"",
            primary_secret=secret,
        )
        is True
    )

    assert (
        verifier.verify(
            strategy=VerificationStrategy.BEARER_TOKEN,
            headers={"Authorization": "Bearer wrong_token"},
            query_params={},
            raw_body=b"",
            primary_secret=secret,
        )
        is False
    )

    assert (
        verifier.verify(
            strategy=VerificationStrategy.BEARER_TOKEN,
            headers={"Authorization": "Basic something"},
            query_params={},
            raw_body=b"",
            primary_secret=secret,
        )
        is False
    )


def test_query_token_strategy() -> None:
    verifier = TimingSafeInboundVerifier()
    secret = "query_secret_token"

    assert (
        verifier.verify(
            strategy=VerificationStrategy.QUERY_TOKEN,
            headers={},
            query_params={"token": secret},
            raw_body=b"",
            primary_secret=secret,
        )
        is True
    )

    assert (
        verifier.verify(
            strategy=VerificationStrategy.QUERY_TOKEN,
            headers={},
            query_params={"token": "invalid"},
            raw_body=b"",
            primary_secret=secret,
        )
        is False
    )


def test_hmac_sha256_strategy() -> None:
    verifier = TimingSafeInboundVerifier()
    secret = "hmac_signing_key_456"
    raw_body = b'{"msg":"hello world"}'
    sig = sign_payload(secret, raw_body)

    headers = {"X-Signature-256": f"sha256={sig}"}
    assert (
        verifier.verify(
            strategy=VerificationStrategy.HMAC_SHA256,
            headers=headers,
            query_params={},
            raw_body=raw_body,
            primary_secret=secret,
        )
        is True
    )

    # Tampered body fails
    assert (
        verifier.verify(
            strategy=VerificationStrategy.HMAC_SHA256,
            headers=headers,
            query_params={},
            raw_body=b'{"msg":"tampered"}',
            primary_secret=secret,
        )
        is False
    )


def test_mutual_tls_strategy() -> None:
    verifier = TimingSafeInboundVerifier()
    # Verified transport origin present with SUCCESS
    assert (
        verifier.verify(
            strategy=VerificationStrategy.MUTUAL_TLS,
            headers={
                "X-SSL-Client-Verify": "SUCCESS",
                "X-SSL-Client-SHA256": "abcdef123456",
            },
            query_params={},
            raw_body=b"",
            primary_secret="not_used",
        )
        is True
    )

    # Missing verified transport context rejected even if header claims SUCCESS
    assert (
        verifier.verify(
            strategy=VerificationStrategy.MUTUAL_TLS,
            headers={"X-SSL-Client-Verify": "SUCCESS"},
            query_params={},
            raw_body=b"",
            primary_secret="not_used",
        )
        is False
    )

    # Failed verification
    assert (
        verifier.verify(
            strategy=VerificationStrategy.MUTUAL_TLS,
            headers={
                "X-SSL-Client-Verify": "FAILED",
                "X-SSL-Client-SHA256": "abcdef123456",
            },
            query_params={},
            raw_body=b"",
            primary_secret="not_used",
        )
        is False
    )
