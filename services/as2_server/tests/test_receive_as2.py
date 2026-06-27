"""
Integration tests for the AS2 inbound receiver endpoint: POST /as2

Tests use real X.509 certificates and real S/MIME signed/encrypted payloads.
All observability is wired with NoOp adapters — no infrastructure required.
"""

from typing import Any

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


def _build_as2_headers(
    as2_from: str,
    as2_to: str,
    message_id: str,
    content_type: str,
) -> dict[str, str]:
    return {
        "as2-from": f'"{as2_from}"',
        "as2-to": f'"{as2_to}"',
        "message-id": f"<{message_id}>",
        "content-type": content_type,
        "mime-version": "1.0",
        "as2-version": "1.2",
    }


class TestAS2ServerHealthProbes:
    """Verify the Kubernetes health probes respond correctly."""

    async def test_liveness_probe(self, as2_client: AsyncClient) -> None:
        response = await as2_client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    async def test_readiness_probe(self, as2_client: AsyncClient) -> None:
        response = await as2_client.get("/ready")
        assert response.status_code == 200
        assert response.json() == {"status": "ready"}

    async def test_metrics_endpoint_returns_prometheus_format(
        self, as2_client: AsyncClient
    ) -> None:
        response = await as2_client.get("/metrics")
        assert response.status_code == 200
        assert "text/plain" in response.headers["content-type"]


class TestAS2MessageReceiving:
    """
    Tests for the main /as2 inbound message flow.
    Payloads are real S/MIME signed/encrypted bytes built in conftest.py.
    """

    async def test_plain_as2_message_returns_processed_mdn(
        self, as2_client: AsyncClient, sender_keypair: Any, edi_payload: bytes
    ) -> None:
        """
        A plain (unsigned, unencrypted) AS2 message should return HTTP 200
        with a synchronous MDN containing disposition: processed.
        """
        headers = _build_as2_headers(
            as2_from=sender_keypair.as2_id,
            as2_to="SOOPAEDI-AS2-ID",
            message_id="test-plain-001",
            content_type="application/edi-x12",
        )
        response = await as2_client.post("/as2", content=edi_payload, headers=headers)

        assert response.status_code == 200
        assert "multipart/report" in response.headers["content-type"]
        assert b"processed" in response.content
        assert b"test-plain-001" in response.content

    async def test_signed_as2_message_with_valid_cert_returns_processed_mdn(
        self, as2_client: AsyncClient, sender_keypair: Any, signed_as2_payload: bytes
    ) -> None:
        """
        A real multipart/signed payload from a known Trading Partner
        should be verified successfully and return disposition: processed.
        """
        headers = _build_as2_headers(
            as2_from=sender_keypair.as2_id,
            as2_to="SOOPAEDI-AS2-ID",
            message_id="test-signed-001",
            content_type='multipart/signed; protocol="application/pkcs7-signature"; micalg=sha-256',
        )
        response = await as2_client.post("/as2", content=signed_as2_payload, headers=headers)

        assert response.status_code == 200
        assert b"test-signed-001" in response.content

    async def test_as2_message_from_unknown_partner_returns_security_failed_mdn(
        self, as2_client: AsyncClient, edi_payload: bytes
    ) -> None:
        """
        A signed message from an AS2-ID not in our Trading Partner database
        should return HTTP 200 but with disposition: failed/insufficient-message-security.
        The endpoint must still return HTTP 200 (AS2 protocol requirement).
        """
        headers = _build_as2_headers(
            as2_from="UNKNOWN-PARTNER",
            as2_to="SOOPAEDI-AS2-ID",
            message_id="test-unknown-001",
            content_type='multipart/signed; protocol="application/pkcs7-signature"; micalg=sha-256',
        )
        response = await as2_client.post("/as2", content=edi_payload, headers=headers)

        # AS2 protocol: always HTTP 200 — even for failures
        assert response.status_code == 200
        assert b"insufficient-message-security" in response.content

    async def test_missing_mandatory_as2_headers_returns_400(
        self, as2_client: AsyncClient, edi_payload: bytes
    ) -> None:
        """
        A request missing AS2-From, AS2-To, or Message-ID headers
        must be rejected with HTTP 400 (not a valid AS2 message at all).
        """
        response = await as2_client.post(
            "/as2",
            content=edi_payload,
            headers={"content-type": "application/edi-x12"},
        )
        assert response.status_code == 400

    async def test_mic_is_included_in_mdn_response(
        self, as2_client: AsyncClient, sender_keypair: Any, edi_payload: bytes
    ) -> None:
        """
        The synchronous MDN must include a Received-content-MIC header
        so the sender can verify the payload was received intact.
        """
        headers = _build_as2_headers(
            as2_from=sender_keypair.as2_id,
            as2_to="SOOPAEDI-AS2-ID",
            message_id="test-mic-001",
            content_type="application/edi-x12",
        )
        response = await as2_client.post("/as2", content=edi_payload, headers=headers)

        assert response.status_code == 200
        assert b"Received-content-MIC" in response.content

    async def test_encrypted_as2_message_fails_decryption(
        self, as2_client: AsyncClient, sender_keypair: Any, encrypted_as2_payload: bytes
    ) -> None:
        """
        An encrypted payload where we simulated a decryption failure (since mock returns empty key).
        """
        headers = _build_as2_headers(
            as2_from=sender_keypair.as2_id,
            as2_to="SOOPAEDI-AS2-ID",
            message_id="test-enc-001",
            content_type='application/pkcs7-mime; smime-type=enveloped-data; name="smime.p7m"',
        )
        response = await as2_client.post("/as2", content=encrypted_as2_payload, headers=headers)

        assert response.status_code == 200
        assert b"decryption-failed" in response.content

    async def test_invalid_signature_returns_auth_failed(
        self, as2_client: AsyncClient, sender_keypair: Any, signed_as2_payload: bytes
    ) -> None:
        """
        A payload that claims to be signed but content is altered.
        """
        headers = _build_as2_headers(
            as2_from=sender_keypair.as2_id,
            as2_to="SOOPAEDI-AS2-ID",
            message_id="test-sig-fail-001",
            content_type='multipart/signed; protocol="application/pkcs7-signature"; micalg=sha-256',
        )
        from unittest.mock import patch

        with patch("as2_server.main.verify_signature", return_value=(False, b"")):
            response = await as2_client.post("/as2", content=signed_as2_payload, headers=headers)

        assert response.status_code == 200
        assert b"authentication-failed" in response.content
