import datetime
import re

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from edi.adapters.outbound.security.smime import sign_payload, verify_signature
from edi.domain.enums import As2SignatureAlgorithm


@pytest.fixture
def keypair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    # We must use UTC timezone for certificate generation to avoid deprecation warnings
    # and ensure compatibility.
    now = datetime.datetime.now(datetime.UTC)

    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test")]))
        .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test")]))
        .public_key(private_key.public_key())
        .serial_number(123)
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=10))
        .sign(private_key, hashes.SHA256())
    )

    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    return private_pem, cert_pem


def test_sign_payload_strict_crlf_formatting(keypair):
    """
    Ensures that the output of sign_payload strictly uses \r\n for MIME boundaries
    and does not introduce \n canonicalization bugs that break OpenAS2 verification.
    """
    private_pem, cert_pem = keypair
    payload = b"Content-Type: application/edi-x12\r\nContent-Transfer-Encoding: binary\r\n\r\nISA*00*TEST..."

    signed_output = sign_payload(
        payload=payload,
        private_key_pem=private_pem,
        public_cert_pem=cert_pem,
        algorithm=As2SignatureAlgorithm.SHA256,
    )

    # Verify that there are no standalone \n boundaries (all \n must be preceded by \r)
    assert not re.search(b"(?<!\r)\n--", signed_output), (
        "Found invalid Unix newline before boundary!"
    )
    assert b"\r\n--" in signed_output, "Strict CRLF boundary is missing!"

    # Verify the payload is untouched inside the S/MIME wrapper
    assert payload in signed_output, "Original payload was canonicalized or modified!"


def test_sign_and_verify_cycle(keypair):
    """
    Ensures that the detached signature we generate with cryptography can be natively
    verified using our inbound endesive verifier (which simulates BouncyCastle behavior).
    """
    private_pem, cert_pem = keypair
    payload = b"Content-Type: application/edi-x12\r\nContent-Transfer-Encoding: binary\r\n\r\nISA*00*TEST..."

    signed_output = sign_payload(
        payload=payload,
        private_key_pem=private_pem,
        public_cert_pem=cert_pem,
        algorithm=As2SignatureAlgorithm.SHA256,
    )

    is_valid, verified_payload = verify_signature(
        signed_data=signed_output,
        public_cert_pem=cert_pem,
    )

    assert is_valid is True
    assert verified_payload == payload
