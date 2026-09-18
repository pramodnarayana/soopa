import socket

import pytest
from pytest_httpserver import HTTPServer

from edi.adapters.outbound.http.httpx_as2_tester_adapter import HttpxAS2TesterAdapter


@pytest.fixture
def adapter():
    return HttpxAS2TesterAdapter()


@pytest.fixture
def local_adapter():
    return HttpxAS2TesterAdapter(allow_private_ips=True)


VALID_MDN = b"""\
------=_Part_0
Content-Type: text/plain

The MDN receipt
------=_Part_0
Content-Type: message/disposition-notification

Reporting-UA: test
Original-Recipient: rfc822; YOU
Final-Recipient: rfc822; YOU
Original-Message-ID: <123>
Disposition: automatic-action/MDN-sent-automatically; processed

------=_Part_0--
"""


@pytest.mark.asyncio
async def test_test_connection_success(
    local_adapter: HttpxAS2TesterAdapter, httpserver: HTTPServer
):
    # Set up the real HTTP server to respond with a 200 and a dummy MDN
    httpserver.expect_request("/as2", method="POST").respond_with_data(
        VALID_MDN,
        status=200,
        headers={
            "Content-Type": 'multipart/report; report-type=disposition-notification; boundary="----=_Part_0"'
        },
    )

    success, disposition, payload_str, full_mdn = await local_adapter.test_connection(
        remote_url=httpserver.url_for("/as2"),
        as2_from="ME",
        as2_to="YOU",
        local_private_key_pem=None,
        local_cert_pem=None,
        remote_cert_pem=None,
        encryption_algorithm="none",
        signature_algorithm="none",
    )

    assert success is True
    assert disposition == "automatic-action/MDN-sent-automatically; processed"
    assert payload_str is not None
    assert full_mdn is not None


@pytest.mark.asyncio
async def test_test_connection_build_fail(adapter: HttpxAS2TesterAdapter):
    # Pass invalid algorithm to trigger build failure organically
    success, reason, _payload, _mdn = await adapter.test_connection(
        remote_url="http://example.com/as2",
        as2_from="ME",
        as2_to="YOU",
        local_private_key_pem=None,
        local_cert_pem=None,
        remote_cert_pem=b"fakecert",
        encryption_algorithm="INVALID_ALG",
        signature_algorithm="none",
    )

    assert success is False
    assert "Failed to build AS2 message" in reason


@pytest.mark.asyncio
async def test_test_connection_http_500(
    local_adapter: HttpxAS2TesterAdapter, httpserver: HTTPServer
):
    httpserver.expect_request("/as2", method="POST").respond_with_data(
        "internal server error", status=500
    )

    success, reason, _payload, _mdn = await local_adapter.test_connection(
        remote_url=httpserver.url_for("/as2"),
        as2_from="ME",
        as2_to="YOU",
        local_private_key_pem=None,
        local_cert_pem=None,
        remote_cert_pem=None,
        encryption_algorithm="none",
        signature_algorithm="none",
    )

    assert success is False
    assert "HTTP 500" in reason


@pytest.mark.asyncio
async def test_test_connection_parse_fail(
    local_adapter: HttpxAS2TesterAdapter, httpserver: HTTPServer
):
    # Respond with plain text to cause organic MDN parsing failure
    httpserver.expect_request("/as2", method="POST").respond_with_data(
        "not a valid mdn multipart message",
        status=200,
        headers={"Content-Type": "text/plain"},
    )

    success, reason, _payload, _mdn = await local_adapter.test_connection(
        remote_url=httpserver.url_for("/as2"),
        as2_from="ME",
        as2_to="YOU",
        local_private_key_pem=None,
        local_cert_pem=None,
        remote_cert_pem=None,
        encryption_algorithm="none",
        signature_algorithm="none",
    )

    assert success is False
    assert "parse error" in reason.lower() or "missing content-type" in reason.lower()


@pytest.mark.asyncio
async def test_test_connection_ssrf_fail(adapter: HttpxAS2TesterAdapter):
    # A private IP will fail the real SSRF check
    success, reason, _payload, _mdn = await adapter.test_connection(
        remote_url="http://192.168.1.5",
        as2_from="ME",
        as2_to="YOU",
        local_private_key_pem=None,
        local_cert_pem=None,
        remote_cert_pem=None,
        encryption_algorithm="none",
        signature_algorithm="none",
    )

    assert success is False
    assert "SSRF" in reason


@pytest.mark.asyncio
async def test_test_connection_http_fail(
    local_adapter: HttpxAS2TesterAdapter, httpserver: HTTPServer
):
    with socket.socket() as unused_socket:
        unused_socket.bind((httpserver.host, 0))
        unused_port = unused_socket.getsockname()[1]
    remote_url = f"http://{httpserver.host}:{unused_port}/closed"

    success, reason, _payload, _mdn = await local_adapter.test_connection(
        remote_url=remote_url,
        as2_from="ME",
        as2_to="YOU",
        local_private_key_pem=None,
        local_cert_pem=None,
        remote_cert_pem=None,
        encryption_algorithm="none",
        signature_algorithm="none",
    )

    assert success is False
    assert "refused" in reason.lower() or "connect" in reason.lower()


# Simulates a signed MDN as returned by OpenAS2 and other signing-enabled AS2 servers.
# Per RFC 4130 §7.4, the multipart/report is wrapped inside a multipart/signed envelope.
SIGNED_MDN_INNER = (
    'Content-Type: multipart/report; report-type=disposition-notification; boundary="----=_Part_0"\r\n'
    "Content-Transfer-Encoding: binary\r\n\r\n"
    "------=_Part_0\r\n"
    "Content-Type: text/plain\r\n\r\n"
    "The MDN receipt\r\n"
    "------=_Part_0\r\n"
    "Content-Type: message/disposition-notification\r\n\r\n"
    "Reporting-UA: OpenAS2\r\n"
    "Original-Recipient: rfc822; YOU\r\n"
    "Final-Recipient: rfc822; YOU\r\n"
    "Original-Message-ID: <123>\r\n"
    "Disposition: automatic-action/MDN-sent-automatically; processed\r\n\r\n"
    "------=_Part_0--\r\n"
)

SIGNED_MDN_BODY = (
    "------=_sig_boundary\r\n" + SIGNED_MDN_INNER + "------=_sig_boundary\r\n"
    "Content-Type: application/pkcs7-signature; name=smime.p7s\r\n"
    "Content-Transfer-Encoding: base64\r\n\r\n"
    "FAKESIGNATUREBYTES==\r\n"
    "------=_sig_boundary--\r\n"
)


@pytest.mark.asyncio
async def test_test_connection_signed_mdn(
    local_adapter: HttpxAS2TesterAdapter, httpserver: HTTPServer
):
    """
    Validates that the tester correctly accepts a signed MDN (multipart/signed)
    as returned by OpenAS2 and other RFC 4130 §7.4-compliant AS2 servers.
    Previously this was incorrectly rejected with "MDN parse error: missing Content-Type multipart/report".
    """
    httpserver.expect_request("/as2", method="POST").respond_with_data(
        SIGNED_MDN_BODY.encode("ascii"),
        status=200,
        headers={
            "Content-Type": (
                'multipart/signed; protocol="application/pkcs7-signature"; '
                'micalg=sha-256; boundary="----=_sig_boundary"'
            )
        },
    )

    success, disposition, payload_str, full_mdn = await local_adapter.test_connection(
        remote_url=httpserver.url_for("/as2"),
        as2_from="ME",
        as2_to="YOU",
        local_private_key_pem=None,
        local_cert_pem=None,
        remote_cert_pem=None,
        encryption_algorithm="none",
        signature_algorithm="none",
    )

    assert success is True
    assert disposition == "automatic-action/MDN-sent-automatically; processed"
    assert payload_str is not None
    assert full_mdn is not None
