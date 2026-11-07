"""Unit tests for L1 Inbound verifiers, decoders, and acknowledgment adapters."""

from __future__ import annotations

import hashlib
import hmac
import time

from ip.engine.adapters.outbound.inbound.ack import JsonInboundAck, XmlSoapInboundAck
from ip.engine.adapters.outbound.inbound.decoders import StandardInboundPayloadDecoder
from ip.engine.adapters.outbound.inbound.verifiers import (
    HmacSignatureVerifier,
    NoOpVerifier,
    StaticTokenVerifier,
)


def test_hmac_signature_verifier_valid() -> None:
    secret = "webhook_secret_key"
    payload = b'{"event":"charge.successful","amount":100}'
    expected_sig = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()

    verifier = HmacSignatureVerifier(
        signature_header="X-Signature-SHA256",
        timestamp_header=None,
        prefix="",
    )
    headers = {"X-Signature-SHA256": expected_sig}

    res = verifier.verify(headers=headers, raw_body=payload, secret=secret)
    assert res.is_ok is True
    assert res.value is True


def test_hmac_signature_verifier_invalid() -> None:
    secret = "webhook_secret_key"
    payload = b'{"event":"charge.successful","amount":100}'

    verifier = HmacSignatureVerifier(
        signature_header="X-Signature-SHA256",
        timestamp_header=None,
        prefix="",
    )
    headers = {"X-Signature-SHA256": "wrong_signature"}

    res = verifier.verify(headers=headers, raw_body=payload, secret=secret)
    assert res.is_err is True


def test_hmac_signature_verifier_missing_header() -> None:
    verifier = HmacSignatureVerifier(
        signature_header="X-Signature-SHA256",
        timestamp_header=None,
        prefix="",
    )
    res = verifier.verify(headers={}, raw_body=b"test", secret="secret")
    assert res.is_err is True


def test_hmac_signature_verifier_empty_secret() -> None:
    verifier = HmacSignatureVerifier(
        signature_header="X-Signature-SHA256",
        timestamp_header=None,
        prefix="",
    )
    res = verifier.verify(headers={"x-signature-sha256": "abc"}, raw_body=b"test", secret="")
    assert res.is_err is True


def test_hmac_signature_verifier_with_timestamp() -> None:
    secret = "test_webhook_secret"
    payload = b'{"msg":"hello"}'
    ts = str(int(time.time()))
    signed_content = f"{ts}.".encode() + payload
    sig = hmac.new(secret.encode("utf-8"), signed_content, hashlib.sha256).hexdigest()

    verifier = HmacSignatureVerifier(
        signature_header="X-Signature",
        timestamp_header="X-Timestamp",
        prefix="",
    )
    res = verifier.verify(
        headers={"X-Signature": sig, "X-Timestamp": ts},
        raw_body=payload,
        secret=secret,
    )
    assert res.is_ok is True


def test_static_token_verifier() -> None:
    verifier = StaticTokenVerifier(header_name="X-API-Key")
    assert (
        verifier.verify(headers={"x-api-key": "secret123"}, raw_body=b"", secret="secret123").is_ok
        is True
    )
    assert (
        verifier.verify(headers={"x-api-key": "wrong"}, raw_body=b"", secret="secret123").is_err
        is True
    )
    assert verifier.verify(headers={}, raw_body=b"", secret="secret123").is_err is True


def test_noop_verifier() -> None:
    verifier = NoOpVerifier()
    assert verifier.verify(headers={}, raw_body=b"arbitrary", secret="").is_ok is True


def test_json_payload_decoder() -> None:
    decoder = StandardInboundPayloadDecoder()
    decoded = decoder.decode(
        content_type="application/json", raw_body=b'{"name":"Solar Farm Alpha","output_kw":500}'
    )
    assert decoded.is_ok
    assert isinstance(decoded.value, dict)
    assert decoded.value["name"] == "Solar Farm Alpha"
    assert decoded.value["output_kw"] == 500

    fallback = decoder.decode(content_type="text/plain", raw_body=b"invalid-json")
    assert fallback.is_ok
    assert isinstance(fallback.value, dict)
    assert fallback.value["raw_text"] == "invalid-json"


def test_json_ack_builder() -> None:
    builder = JsonInboundAck(status_code=202)
    ack = builder.build_ack(app_id="stripe", payload={"id": "evt_1"}, headers={})
    assert ack.status_code == 202
    assert ack.headers["Content-Type"] == "application/json"
    assert isinstance(ack.body, dict)
    assert ack.body["status"] == "accepted"


def test_xml_soap_ack_builder() -> None:
    builder = XmlSoapInboundAck()
    ack = builder.build_ack(app_id="custom_soap", payload={}, headers={})
    assert ack.status_code == 200
    assert ack.headers["Content-Type"] == "text/xml; charset=utf-8"
    assert "<notificationsResponse" in str(ack.body)
    assert "<Ack>true</Ack>" in str(ack.body)
