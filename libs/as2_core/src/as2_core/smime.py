"""
S/MIME cryptographic operations for AS2.
Handles encryption, decryption, and signature verification.
"""

import os
import subprocess
import tempfile


def decrypt_payload(encrypted_data: bytes, private_key_pem: bytes, public_cert_pem: bytes) -> bytes:
    """
    Decrypts an S/MIME PKCS#7 enveloped data payload using OpenSSL as a robust backend.
    In enterprise AS2, handling the myriad of legacy S/MIME wrappers is safest via OpenSSL smime.
    """
    with (
        tempfile.NamedTemporaryFile(delete=False) as key_file,
        tempfile.NamedTemporaryFile(delete=False) as cert_file,
        tempfile.NamedTemporaryFile(delete=False) as in_file,
    ):
        key_file.write(private_key_pem)
        cert_file.write(public_cert_pem)
        in_file.write(encrypted_data)

        key_file.flush()
        cert_file.flush()
        in_file.flush()

    try:
        # openssl smime -decrypt -in <infile> -recip <certfile> -inkey <keyfile> -inform DER/SMIME
        result = subprocess.run(
            [
                "openssl",
                "smime",
                "-decrypt",
                "-in",
                in_file.name,
                "-recip",
                cert_file.name,
                "-inkey",
                key_file.name,
                "-inform",
                "SMIME",
            ],
            capture_output=True,
            check=True,
        )
        return result.stdout
    finally:
        os.unlink(key_file.name)
        os.unlink(cert_file.name)
        os.unlink(in_file.name)


def verify_signature(signed_data: bytes, public_cert_pem: bytes) -> tuple[bool, bytes]:
    """
    Verifies an S/MIME detached or attached signature.
    Returns (is_valid, extracted_payload).
    """
    with (
        tempfile.NamedTemporaryFile(delete=False) as cert_file,
        tempfile.NamedTemporaryFile(delete=False) as in_file,
    ):
        cert_file.write(public_cert_pem)
        in_file.write(signed_data)

        cert_file.flush()
        in_file.flush()

    try:
        result = subprocess.run(
            [
                "openssl",
                "smime",
                "-verify",
                "-in",
                in_file.name,
                "-certfile",
                cert_file.name,
                "-noverify",  # AS2 often uses self-signed, trust is handled at the DB level
                "-inform",
                "SMIME",
            ],
            capture_output=True,
            check=True,
        )
        return True, result.stdout
    except subprocess.CalledProcessError:
        return False, b""
    finally:
        os.unlink(cert_file.name)
        os.unlink(in_file.name)


def sign_payload(payload: bytes, private_key_pem: bytes, public_cert_pem: bytes) -> bytes:
    """
    Signs a payload for AS2 transmission (S/MIME multipart/signed).
    """
    with (
        tempfile.NamedTemporaryFile(delete=False) as key_file,
        tempfile.NamedTemporaryFile(delete=False) as cert_file,
        tempfile.NamedTemporaryFile(delete=False) as in_file,
    ):
        key_file.write(private_key_pem)
        cert_file.write(public_cert_pem)
        in_file.write(payload)

        key_file.flush()
        cert_file.flush()
        in_file.flush()

    try:
        result = subprocess.run(
            [
                "openssl",
                "smime",
                "-sign",
                "-in",
                in_file.name,
                "-signer",
                cert_file.name,
                "-inkey",
                key_file.name,
                "-outform",
                "SMIME",
            ],
            capture_output=True,
            check=True,
        )
        return result.stdout
    finally:
        os.unlink(key_file.name)
        os.unlink(cert_file.name)
        os.unlink(in_file.name)
