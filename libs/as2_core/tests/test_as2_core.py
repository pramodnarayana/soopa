"""
Pure unit tests for libs/as2_core.

These tests have ZERO external dependencies:
  - No database
  - No web server
  - No OpenTelemetry infrastructure
All inputs and outputs are raw Python bytes/dicts.
"""

import pytest
from as2_core.mdn import calculate_mic, generate_mdn, render_mdn_report
from as2_core.message import AS2Message
from as2_core.parser import parse_as2_request

EDI_PAYLOAD = b"ISA*00*TEST...\nGS*PO*...\nST*850*0001\nSE*1*0001\nGE*1*1\nIEA*1*000000001\n"


class TestAS2Parser:
    """Unit tests for the pure AS2 HTTP request parser."""

    def test_parses_minimal_valid_as2_headers(self):
        headers = {
            "as2-from": '"PARTNER"',
            "as2-to": '"SOOPAEDI"',
            "message-id": "<msg-001@test>",
            "content-type": "application/edi-x12",
        }
        msg = parse_as2_request(headers, EDI_PAYLOAD)

        assert msg.as2_from == "PARTNER"
        assert msg.as2_to == "SOOPAEDI"
        assert msg.message_id == "msg-001@test"
        assert msg.payload == EDI_PAYLOAD

    def test_detects_encrypted_content_type(self):
        headers = {
            "as2-from": '"PARTNER"',
            "as2-to": '"SOOPAEDI"',
            "message-id": "<msg-enc-001>",
            "content-type": 'application/pkcs7-mime; smime-type=enveloped-data; name="smime.p7m"',
        }
        msg = parse_as2_request(headers, b"encrypted-bytes")

        assert msg.is_encrypted is True
        assert msg.is_signed is False

    def test_detects_signed_content_type(self):
        headers = {
            "as2-from": '"PARTNER"',
            "as2-to": '"SOOPAEDI"',
            "message-id": "<msg-sig-001>",
            "content-type": 'multipart/signed; protocol="application/pkcs7-signature"; micalg=sha-256',
        }
        msg = parse_as2_request(headers, b"signed-bytes")

        assert msg.is_signed is True
        assert msg.is_encrypted is False

    def test_raises_on_missing_as2_from(self):
        headers = {
            "as2-to": '"SOOPAEDI"',
            "message-id": "<msg-001>",
            "content-type": "application/edi-x12",
        }
        with pytest.raises(ValueError, match="Missing mandatory AS2 headers"):
            parse_as2_request(headers, EDI_PAYLOAD)

    def test_raises_on_missing_message_id(self):
        headers = {
            "as2-from": '"PARTNER"',
            "as2-to": '"SOOPAEDI"',
            "content-type": "application/edi-x12",
        }
        with pytest.raises(ValueError, match="Missing mandatory AS2 headers"):
            parse_as2_request(headers, EDI_PAYLOAD)

    def test_strips_quotes_from_as2_ids(self):
        """AS2 IDs in HTTP headers are quoted — the parser must strip them."""
        headers = {
            "as2-from": '"  PARTNER-ID  "',
            "as2-to": '"SOOPAEDI"',
            "message-id": "<msg-001>",
            "content-type": "application/edi-x12",
        }
        msg = parse_as2_request(headers, EDI_PAYLOAD)
        assert msg.as2_from == "PARTNER-ID"


class TestMICCalculation:
    """Unit tests for MIC (Message Integrity Check) calculation."""

    def test_sha256_mic_is_base64_encoded_sha256(self):
        import base64
        import hashlib

        payload = b"hello-edi-world"
        mic = calculate_mic(payload, mic_alg="sha256")
        expected_b64 = base64.b64encode(hashlib.sha256(payload).digest()).decode()
        assert mic.startswith(expected_b64)
        assert "sha256" in mic

    def test_sha1_mic_uses_correct_algorithm(self):
        import base64
        import hashlib

        payload = b"test-payload"
        mic = calculate_mic(payload, mic_alg="sha1")
        expected_b64 = base64.b64encode(hashlib.sha1(payload).digest()).decode()
        assert mic.startswith(expected_b64)
        assert "sha1" in mic

    def test_unsupported_algorithm_raises(self):
        with pytest.raises(ValueError, match="Unsupported MIC algorithm"):
            calculate_mic(b"data", mic_alg="md4")

    def test_mic_format_contains_comma_separator(self):
        """MIC must be in the format: <base64>, <algorithm> per RFC 4130."""
        mic = calculate_mic(b"payload", mic_alg="sha256")
        parts = mic.split(", ")
        assert len(parts) == 2
        assert parts[1] == "sha256"


class TestMDNGeneration:
    """Unit tests for MDN (Message Disposition Notification) generation."""

    def _make_message(self) -> AS2Message:
        return AS2Message(
            message_id="original-msg-001",
            as2_from="PARTNER",
            as2_to="SOOPAEDI",
            payload=EDI_PAYLOAD,
        )

    def test_mdn_swaps_from_and_to(self):
        """The MDN must swap AS2-From and AS2-To (we reply to the sender)."""
        msg = self._make_message()
        mdn = generate_mdn(msg, disposition="automatic-action/MDN-sent-automatically; processed")
        assert mdn.headers["AS2-From"] == "SOOPAEDI"
        assert mdn.headers["AS2-To"] == "PARTNER"

    def test_mdn_includes_original_message_id(self):
        msg = self._make_message()
        mdn = generate_mdn(msg, disposition="processed")
        assert mdn.original_message_id == "original-msg-001"

    def test_mdn_calculates_mic_when_payload_present(self):
        msg = self._make_message()
        mdn = generate_mdn(msg, disposition="processed")
        assert mdn.mic is not None
        assert len(mdn.mic) > 0

    def test_mdn_mic_is_none_when_payload_empty(self):
        msg = AS2Message(
            message_id="empty-001",
            as2_from="PARTNER",
            as2_to="SOOPAEDI",
            payload=b"",
        )
        mdn = generate_mdn(msg, disposition="processed")
        assert mdn.mic is None

    def test_render_mdn_report_contains_required_fields(self):
        msg = self._make_message()
        mdn = generate_mdn(msg, disposition="automatic-action/MDN-sent-automatically; processed")
        report = render_mdn_report(mdn)

        assert b"message/disposition-notification" in report
        assert b"original-msg-001" in report
        assert b"Received-content-MIC" in report

    def test_render_mdn_report_for_failure_contains_disposition(self):
        msg = self._make_message()
        mdn = generate_mdn(
            msg, disposition="automatic-action/MDN-sent-automatically; failed/authentication-failed"
        )
        report = render_mdn_report(mdn)

        assert b"failed/authentication-failed" in report
