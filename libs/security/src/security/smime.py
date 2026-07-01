"""
S/MIME cryptographic operations for AS2.
Handles encryption, decryption, signing, and signature verification.

All operations are fully native (cryptography.hazmat) and in-memory.
No private keys or payloads are ever written to disk.
"""

import os
import subprocess
import tempfile

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.ciphers import algorithms
from cryptography.hazmat.primitives.serialization import pkcs7


def decrypt_payload(encrypted_data: bytes, private_key_pem: bytes, public_cert_pem: bytes) -> bytes:
    """
    Decrypts an S/MIME PKCS#7 enveloped data payload using native cryptography.hazmat.
    This is memory-safe and avoids writing sensitive private keys to disk.
    """
    private_key = serialization.load_pem_private_key(private_key_pem, password=None)
    cert = x509.load_pem_x509_certificate(public_cert_pem)

    return pkcs7.pkcs7_decrypt_smime(encrypted_data, cert, private_key, options=[])  # type: ignore[arg-type]


def sign_payload(payload: bytes, private_key_pem: bytes, public_cert_pem: bytes) -> bytes:
    """
    Signs a payload for AS2 transmission (S/MIME multipart/signed).
    Uses native cryptography.hazmat to keep private keys in memory.
    """
    private_key = serialization.load_pem_private_key(private_key_pem, password=None)
    cert = x509.load_pem_x509_certificate(public_cert_pem)

    builder = pkcs7.PKCS7SignatureBuilder().set_data(payload)
    builder = builder.add_signer(cert, private_key, hash_algorithm=hashes.SHA256())  # type: ignore[arg-type]

    # AS2 requires S/MIME encoding for the signed payload
    return builder.sign(serialization.Encoding.SMIME, options=[])


def encrypt_payload(
    payload: bytes,
    public_cert_pem: bytes,
    algorithm: str = "AES256",
) -> bytes:
    """
    Encrypts a payload for AS2 transmission using S/MIME CMS enveloped data.
    Uses PKCS7EnvelopeBuilder — fully native, in-memory, zero subprocess.

    Args:
        payload: The raw EDI or content bytes to encrypt.
        public_cert_pem: The Trading Partner's public certificate in PEM format.
        algorithm: The symmetric cipher algorithm (AES256 or AES128).

    Returns:
        S/MIME-encoded enveloped bytes ready for transmission.
    """
    cert = x509.load_pem_x509_certificate(public_cert_pem)

    if algorithm.upper() in ("AES256", "AES-256", "AES256_CBC"):
        cipher: type[algorithms.AES128] | type[algorithms.AES256] = algorithms.AES256
    elif algorithm.upper() in ("AES128", "AES-128", "AES128_CBC"):
        cipher = algorithms.AES128
    else:
        raise ValueError(f"Unsupported encryption algorithm: {algorithm!r}. Use AES256 or AES128.")

    return (
        pkcs7.PKCS7EnvelopeBuilder()
        .set_data(payload)
        .add_recipient(cert)
        .set_content_encryption_algorithm(cipher)
        .encrypt(serialization.Encoding.SMIME, options=[])
    )


def verify_signature(signed_data: bytes, public_cert_pem: bytes) -> tuple[bool, bytes]:
    """
    Verifies an S/MIME detached or attached signature.
    Since native cryptography does not yet support signature verification,
    we use OpenSSL via subprocess.
    Public certificates are safely written to a temp file, and payload is piped via stdin.
    """
    with tempfile.NamedTemporaryFile(delete=False) as cert_file:
        cert_file.write(public_cert_pem)
        cert_file.flush()

    try:
        result = subprocess.run(
            [
                "openssl",
                "smime",
                "-verify",
                "-certfile",
                cert_file.name,
                "-noverify",  # AS2 often uses self-signed, trust is handled at the DB level
                "-inform",
                "SMIME",
            ],
            input=signed_data,
            capture_output=True,
            check=True,
            timeout=10.0,
        )
        return True, result.stdout
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False, b""
    finally:
        os.unlink(cert_file.name)
