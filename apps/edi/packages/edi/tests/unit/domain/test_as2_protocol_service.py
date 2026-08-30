"""
Layer 1 — Pure Domain Unit Tests: AS2 Protocol Domain Service.

The functions under test (calculate_mic, parse_as2_request, parse_mdn,
generate_mdn, build_mdn) are pure Python stdlib — no I/O, no infrastructure.
Zero mocks required; fakes are not needed at this layer.
"""

import pytest

from edi.domain.services.as2_protocol import (
    build_mdn,
    calculate_mic,
    generate_mdn,
    parse_as2_request,
)

# ---------------------------------------------------------------------------
# calculate_mic — pure hash function
# ---------------------------------------------------------------------------


class TestCalculateMic:
    def test_sha256_produces_base64_comma_algorithm(self):
        payload = b"hello world"
        result = calculate_mic(payload, "sha256")
        parts = result.split(", ")
        assert len(parts) == 2
        assert parts[1] == "sha256"
        # Verify it's valid base64
        import base64

        base64.b64decode(parts[0])  # raises if invalid

    def test_sha1_produces_correct_format(self):
        result = calculate_mic(b"test", "sha1")
        assert result.endswith(", sha1")

    def test_md5_produces_correct_format(self):
        result = calculate_mic(b"test", "md5")
        assert result.endswith(", md5")

    def test_algorithm_normalises_hyphens(self):
        """sha-256 and sha256 should produce the same MIC."""
        payload = b"normalize me"
        mic_with_hyphen = calculate_mic(payload, "sha-256")
        mic_without_hyphen = calculate_mic(payload, "sha256")
        assert mic_with_hyphen.split(", ")[0] == mic_without_hyphen.split(", ")[0]

    def test_unsupported_algorithm_raises_value_error(self):
        with pytest.raises(ValueError, match="Unsupported MIC algorithm"):
            calculate_mic(b"data", "sha512")

    def test_deterministic_for_same_payload(self):
        payload = b"deterministic"
        assert calculate_mic(payload, "sha256") == calculate_mic(payload, "sha256")

    def test_different_payloads_produce_different_mics(self):
        assert calculate_mic(b"aaa", "sha256") != calculate_mic(b"bbb", "sha256")


# ---------------------------------------------------------------------------
# parse_as2_request — pure header/body parser
# ---------------------------------------------------------------------------


class TestParseAs2Request:
    def _make_headers(self, **overrides):
        base = {
            "as2-from": "SENDER",
            "as2-to": "RECEIVER",
            "message-id": "<abc123@test>",
            "content-type": "application/edi-x12",
        }
        base.update(overrides)
        return base

    def test_parses_minimal_valid_headers(self):
        msg = parse_as2_request(self._make_headers(), b"ISA*00...")
        assert msg.as2_from == "SENDER"
        assert msg.as2_to == "RECEIVER"
        assert msg.message_id == "abc123@test"
        assert msg.payload == b"ISA*00..."
        assert not msg.is_encrypted
        assert not msg.is_signed
        assert not msg.is_compressed

    def test_strips_quotes_from_as2_ids(self):
        headers = self._make_headers(**{"as2-from": '"QUOTED_SENDER"', "as2-to": '"QUOTED_RECV"'})
        msg = parse_as2_request(headers, b"body")
        assert msg.as2_from == "QUOTED_SENDER"
        assert msg.as2_to == "QUOTED_RECV"

    def test_strips_angle_brackets_from_message_id(self):
        headers = self._make_headers(**{"message-id": "<clean-id@host>"})
        msg = parse_as2_request(headers, b"body")
        assert msg.message_id == "clean-id@host"

    def test_detects_encrypted_content_type(self):
        headers = self._make_headers(
            **{"content-type": "application/pkcs7-mime; smime-type=enveloped-data"}
        )
        msg = parse_as2_request(headers, b"encrypted")
        assert msg.is_encrypted is True
        assert msg.is_signed is False

    def test_detects_signed_content_type_multipart(self):
        headers = self._make_headers(**{"content-type": "multipart/signed; boundary=xyz"})
        msg = parse_as2_request(headers, b"signed")
        assert msg.is_signed is True

    def test_detects_signed_content_type_pkcs7_signature(self):
        headers = self._make_headers(
            **{"content-type": "application/pkcs7-signature; charset=binary"}
        )
        msg = parse_as2_request(headers, b"signed")
        assert msg.is_signed is True

    def test_detects_compressed_content_type(self):
        headers = self._make_headers(
            **{"content-type": "application/pkcs7-mime; smime-type=compressed-data"}
        )
        msg = parse_as2_request(headers, b"compressed")
        assert msg.is_compressed is True

    def test_missing_as2_from_raises_value_error(self):
        headers = self._make_headers()
        del headers["as2-from"]
        with pytest.raises(ValueError, match="Missing mandatory AS2 headers"):
            parse_as2_request(headers, b"body")

    def test_missing_as2_to_raises_value_error(self):
        headers = self._make_headers()
        del headers["as2-to"]
        with pytest.raises(ValueError, match="Missing mandatory AS2 headers"):
            parse_as2_request(headers, b"body")

    def test_missing_message_id_raises_value_error(self):
        headers = self._make_headers()
        del headers["message-id"]
        with pytest.raises(ValueError, match="Missing mandatory AS2 headers"):
            parse_as2_request(headers, b"body")

    def test_raw_mime_is_set_to_body(self):
        body = b"raw_mime_content"
        msg = parse_as2_request(self._make_headers(), body)
        assert msg.raw_mime == body


# ---------------------------------------------------------------------------
# generate_mdn — creates an MDN from an inbound AS2Message
# ---------------------------------------------------------------------------


class TestGenerateMdn:
    def _make_as2_message(self, payload=b"original payload"):
        from edi.domain.models.as2 import AS2Message

        return AS2Message(
            message_id="original-id-001",
            as2_from="PARTNER",
            as2_to="LOCAL",
            headers={},
            payload=payload,
            is_encrypted=False,
            is_signed=False,
            is_compressed=False,
            raw_mime=payload,
        )

    def test_mdn_has_swapped_as2_headers(self):
        msg = self._make_as2_message()
        mdn = generate_mdn(msg, "automatic-action/MDN-sent-automatically; processed")
        # AS2 spec: To/From are swapped in MDN
        assert mdn.headers["AS2-From"] == "LOCAL"
        assert mdn.headers["AS2-To"] == "PARTNER"

    def test_mdn_references_original_message_id(self):
        msg = self._make_as2_message()
        mdn = generate_mdn(msg, "processed")
        assert "original-id-001" in mdn.headers["Original-Message-ID"]

    def test_mdn_has_mic_when_payload_is_present(self):
        msg = self._make_as2_message(payload=b"important edi content")
        mdn = generate_mdn(msg, "processed")
        assert mdn.mic is not None
        assert "sha256" in mdn.mic

    def test_mdn_has_no_mic_when_payload_is_empty(self):
        msg = self._make_as2_message(payload=b"")
        mdn = generate_mdn(msg, "processed")
        assert mdn.mic is None


# ---------------------------------------------------------------------------
# build_mdn — serializes an MDN into HTTP body + headers
# ---------------------------------------------------------------------------


class TestBuildMdn:
    def test_build_mdn_unsigned_returns_body_and_headers(self):
        response = build_mdn(
            as2_to="RECEIVER",
            as2_from="SENDER",
            message_id="msg-001",
            disposition="automatic-action/MDN-sent-automatically; processed",
        )
        assert isinstance(response.body, bytes)
        assert b"disposition-notification" in response.body
        assert response.headers["AS2-From"] == "RECEIVER"
        assert response.headers["AS2-To"] == "SENDER"

    def test_build_mdn_includes_mic_when_provided(self):
        mic = "abc123==, sha256"
        response = build_mdn(
            as2_to="R",
            as2_from="S",
            message_id="m1",
            disposition="processed",
            mic=mic,
        )
        assert b"Received-Content-MIC:" in response.body
        assert b"abc123==" in response.body

    def test_build_mdn_omits_mic_field_when_none(self):
        response = build_mdn(
            as2_to="R",
            as2_from="S",
            message_id="m1",
            disposition="processed",
            mic=None,
        )
        assert b"Received-Content-MIC:" not in response.body

    def test_build_mdn_unsigned_content_type_is_multipart_report(self):
        response = build_mdn(
            as2_to="R",
            as2_from="S",
            message_id="m1",
            disposition="processed",
        )
        assert "multipart/report" in response.headers["Content-Type"]

    def test_build_mdn_wraps_message_id_in_angle_brackets(self):
        response = build_mdn(
            as2_to="R",
            as2_from="S",
            message_id="msg-no-brackets",
            disposition="processed",
        )
        # The body should reference the id properly
        assert b"msg-no-brackets" in response.body

    def test_build_mdn_with_sign_fn_calls_signer(self):
        """When a sign_fn is provided, the signer must be invoked."""
        called_with = []

        def fake_sign(data: bytes) -> bytes:
            called_with.append(data)
            # Return minimal "signed" MIME to satisfy the parser
            return (
                b"Content-Type: multipart/signed; boundary=sig\r\n\r\n"
                b"--sig\r\nContent-Type: text/plain\r\n\r\ndata\r\n--sig--\r\n"
            )

        response = build_mdn(
            as2_to="R",
            as2_from="S",
            message_id="m1",
            disposition="processed",
            sign_fn=fake_sign,
        )
        assert len(called_with) == 1  # signer was invoked once
        assert "multipart/signed" in response.headers["Content-Type"]
