import contextlib
import email
import io
import re
import warnings
from collections.abc import Callable
from email import policy
from typing import Protocol, cast

import endesive.verifier
import structlog
from asn1crypto import cms, pem
from asn1crypto import x509 as asn1_x509
from cryptography import x509
from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.serialization import pkcs7
from cryptography.utils import CryptographyDeprecationWarning

from edi.domain.enums import As2EncryptionAlgorithm, As2SignatureAlgorithm


class BlockCipherFactory(Protocol):
    block_size: int

    def __call__(self, key: bytes) -> algorithms.CipherAlgorithm: ...


# Supported ciphers registry for S/MIME encryption
_CIPHER_REGISTRY: dict[str, BlockCipherFactory] = {
    "AES256": cast(BlockCipherFactory, algorithms.AES256),
    "AES-256": cast(BlockCipherFactory, algorithms.AES256),
    "AES256_CBC": cast(BlockCipherFactory, algorithms.AES256),
    "AES128": cast(BlockCipherFactory, algorithms.AES128),
    "AES-128": cast(BlockCipherFactory, algorithms.AES128),
    "AES128_CBC": cast(BlockCipherFactory, algorithms.AES128),
}

# ASN.1 OID to cryptography primitive mapping for native decryption
_ASN1_OID_TO_CIPHER_REGISTRY: dict[str, BlockCipherFactory] = {
    "aes256_cbc": cast(BlockCipherFactory, algorithms.AES256),
    "aes128_cbc": cast(BlockCipherFactory, algorithms.AES128),
}

try:
    from cryptography.hazmat.decrepit.ciphers.algorithms import TripleDES

    _CIPHER_REGISTRY.update(
        {
            "3DES": cast(BlockCipherFactory, TripleDES),
            "DES3": cast(BlockCipherFactory, TripleDES),
            "TRIPLEDES": cast(BlockCipherFactory, TripleDES),
        }
    )
    _ASN1_OID_TO_CIPHER_REGISTRY.update(
        {
            "des_ede3_cbc": cast(BlockCipherFactory, TripleDES),
            "tripledes_3key": cast(BlockCipherFactory, TripleDES),
        }
    )
except ImportError:
    _CIPHER_REGISTRY.update(
        {
            "3DES": cast(BlockCipherFactory, algorithms.TripleDES),
            "DES3": cast(BlockCipherFactory, algorithms.TripleDES),
            "TRIPLEDES": cast(BlockCipherFactory, algorithms.TripleDES),
        }
    )
    _ASN1_OID_TO_CIPHER_REGISTRY.update(
        {
            "des_ede3_cbc": cast(BlockCipherFactory, algorithms.TripleDES),
            "tripledes_3key": cast(BlockCipherFactory, algorithms.TripleDES),
        }
    )

logger = structlog.get_logger(__name__)


def _parse_asn1_content_info(encrypted_data: bytes) -> cms.ContentInfo | None:
    # 1. Try raw bytes (BER/DER)
    with contextlib.suppress(Exception):
        return cms.ContentInfo.load(encrypted_data)

    # 2. Try S/MIME payload extraction
    try:
        msg = email.message_from_bytes(encrypted_data, policy=policy.HTTP)
        pl = msg.get_payload(decode=True)
        if pl:
            return cms.ContentInfo.load(pl)
    except (ValueError, TypeError, KeyError) as exc:
        logger.debug("smime_payload_extraction_fallback_failed", error=str(exc))

    # 3. Try PEM unarmoring
    try:
        _, _, der_bytes = pem.unarmor(encrypted_data)
        return cms.ContentInfo.load(der_bytes)
    except (ValueError, TypeError, KeyError) as exc:
        logger.debug("pem_unarmoring_fallback_failed", error=str(exc))

    return None


def _manual_asn1crypto_decrypt(
    encrypted_data: bytes, private_key: rsa.RSAPrivateKey
) -> bytes | None:
    """
    Ultimate pure-Python native fallback for BouncyCastle BER envelopes.
    Bypasses cryptography's strict Rust PKCS7 parser entirely by manually
    extracting the symmetric key and decrypting the payload using raw primitives.
    (Required for External System Interoperability with legacy B2B partners)
    """
    try:
        content_info = _parse_asn1_content_info(encrypted_data)
        if not content_info:
            raise ValueError(
                "asn1crypto could not parse the payload in any format. Is the binary corrupted?"
            )

        if content_info["content_type"].native != "enveloped_data":
            raise ValueError(f"Expected enveloped_data, got {content_info['content_type'].native}")

        enveloped_data = content_info["content"]
        recipient_infos = enveloped_data["recipient_infos"]

        # Extract the RSA encrypted key
        ktri = recipient_infos[0].chosen
        encrypted_key = ktri["encrypted_key"].native

        # Decrypt symmetric key using RSA Private Key
        symmetric_key = private_key.decrypt(
            encrypted_key,
            padding.PKCS1v15(),  # AS2 PKCS7 always uses PKCS1.5 padding for key transport
        )

        # Get Encrypted Content
        eci = enveloped_data["encrypted_content_info"]
        content_enc_alg = eci["content_encryption_algorithm"]
        alg_oid = content_enc_alg["algorithm"].native
        iv = content_enc_alg["parameters"].native
        ciphertext = eci["encrypted_content"].native

        # Map OID to Cipher
        cipher_class = _ASN1_OID_TO_CIPHER_REGISTRY.get(alg_oid)
        if not cipher_class:
            raise ValueError(f"Unsupported manual cipher OID: {alg_oid}")

        cipher = Cipher(cipher_class(symmetric_key), modes.CBC(iv))
        decryptor = cipher.decryptor()
        padded_plaintext = decryptor.update(ciphertext) + decryptor.finalize()

        # Remove PKCS7 padding
        pad_len = padded_plaintext[-1]
        block_size = cipher_class.block_size
        if pad_len < 1 or pad_len > block_size // 8:
            raise ValueError("Invalid PKCS7 padding length")
        if padded_plaintext[-pad_len:] != bytes([pad_len]) * pad_len:
            raise ValueError("Invalid PKCS7 padding bytes")
        return padded_plaintext[:-pad_len]
    except (ValueError, TypeError, KeyError, IndexError) as e:
        logger.debug("manual_asn1_decryption_failed", error=str(e))
        return None


def decrypt_payload(encrypted_data: bytes, private_key_pem: bytes, public_cert_pem: bytes) -> bytes:
    """
    Decrypts an S/MIME PKCS#7 enveloped data payload using native cryptography.hazmat.
    This is memory-safe and avoids writing sensitive private keys to disk.
    """
    private_key = serialization.load_pem_private_key(private_key_pem, password=None)
    rsa_key = cast(rsa.RSAPrivateKey, private_key)
    cert = x509.load_pem_x509_certificate(public_cert_pem)

    DecryptionStrategy = Callable[
        [bytes, x509.Certificate, rsa.RSAPrivateKey, list[object] | None], bytes
    ]

    strategies: list[tuple[str, DecryptionStrategy]] = [
        ("DER", cast(DecryptionStrategy, pkcs7.pkcs7_decrypt_der)),
        ("SMIME", cast(DecryptionStrategy, pkcs7.pkcs7_decrypt_smime)),
        ("PEM", cast(DecryptionStrategy, pkcs7.pkcs7_decrypt_pem)),
    ]

    for strat_name, strat_func in strategies:
        try:
            return strat_func(encrypted_data, cert, rsa_key, [])
        except (ValueError, TypeError, KeyError, IndexError, UnsupportedAlgorithm) as e:
            logger.debug("decryption_strategy_failed", strategy=strat_name, error=str(e))

    # Enterprise Fallback: Manually parse the ASN.1 tree and decrypt using primitives
    # This is required for external legacy AS2 partners who send envelopes that fail
    # strict Rust parser rules (e.g., older BouncyCastle implementations).
    try:
        if isinstance(private_key, rsa.RSAPrivateKey):
            manual_decrypted = _manual_asn1crypto_decrypt(encrypted_data, private_key)
            if manual_decrypted:
                logger.info(
                    "Successfully decrypted payload using pure Python ASN.1 manual primitives."
                )
                return manual_decrypted
    except (ValueError, TypeError, KeyError, IndexError) as e:
        logger.debug("manual_fallback_decryption_failed", error=str(e))

    raise ValueError("All native decryption strategies failed.")


def sign_payload(
    payload: bytes,
    private_key_pem: bytes,
    public_cert_pem: bytes,
    algorithm: As2SignatureAlgorithm | str = As2SignatureAlgorithm.SHA256,
) -> bytes:
    """
    Signs a payload for AS2 transmission (S/MIME multipart/signed).
    Uses native cryptography.hazmat to keep private keys in memory.
    """
    private_key = serialization.load_pem_private_key(private_key_pem, password=None)
    cert = x509.load_pem_x509_certificate(public_cert_pem)

    alg_map = {
        # AS2 structurally mandates SHA1 for backward compatibility.
        # Ignored S303 inline because Ruff per-file-ignores fails to match in this monorepo context.
        As2SignatureAlgorithm.SHA1: hashes.SHA1(),  # noqa: S303
        As2SignatureAlgorithm.SHA256: hashes.SHA256(),
        As2SignatureAlgorithm.SHA384: hashes.SHA384(),
        As2SignatureAlgorithm.SHA512: hashes.SHA512(),
    }
    if isinstance(algorithm, str):
        algorithm = As2SignatureAlgorithm(algorithm.lower())

    if algorithm not in alg_map:
        raise ValueError(f"Unsupported signature algorithm: {algorithm}")
    hash_alg = alg_map[algorithm]

    builder = pkcs7.PKCS7SignatureBuilder().set_data(payload)

    # Assert structural type for mypy using the expected RSA private key
    # We also cast hash_alg to SHA256 because cryptography's type stub artificially
    # blocks SHA1 (which is required by legacy AS2 partners).
    rsa_key = cast(rsa.RSAPrivateKey, private_key)
    hash_type = cast(hashes.SHA256, hash_alg)
    builder = builder.add_signer(cert, rsa_key, hash_algorithm=hash_type)

    # AS2 requires S/MIME encoding for the signed payload
    return builder.sign(serialization.Encoding.SMIME, options=[])


def encrypt_payload(
    payload: bytes,
    public_cert_pem: bytes,
    algorithm: As2EncryptionAlgorithm | str = As2EncryptionAlgorithm.AES256,
) -> bytes:
    """
    Encrypts a payload for AS2 transmission using S/MIME CMS enveloped data.
    Uses PKCS7EnvelopeBuilder — fully native, in-memory, zero subprocess.
    """
    cert = x509.load_pem_x509_certificate(public_cert_pem)

    if isinstance(algorithm, str):
        algorithm = As2EncryptionAlgorithm(algorithm.lower())

    cipher_class = _CIPHER_REGISTRY.get(algorithm.value.upper())
    if not cipher_class:
        raise ValueError(
            f"Unsupported encryption algorithm: {algorithm.value!r}. Supported: {list(_CIPHER_REGISTRY.keys())}"
        )

    content_alg = cast(type[algorithms.AES128] | type[algorithms.AES256], cipher_class)

    return (
        pkcs7.PKCS7EnvelopeBuilder()
        .set_data(payload)
        .add_recipient(cert)
        .set_content_encryption_algorithm(content_alg)
        .encrypt(serialization.Encoding.SMIME, options=[])
    )


# ---------------------------------------------------------------------------
# Native Signature Verification Core Logic
# ---------------------------------------------------------------------------


def _extract_smime_signature_parts(signed_data: bytes) -> tuple[bytes, bytes]:
    """
    Safely extracts the raw payload and the binary signature from an S/MIME multipart.
    Returns (raw_signed_content, binary_signature).
    """
    msg = email.message_from_bytes(signed_data, policy=policy.default)
    boundary = msg.get_boundary()
    if not boundary:
        raise ValueError("Not a valid multipart/signed entity (missing boundary)")

    boundary_bytes = b"--" + boundary.encode("ascii")
    pattern = re.compile(b"(?:\r\n|\n)" + re.escape(boundary_bytes) + b"(?:\r\n|\n|--)")
    parts = pattern.split(signed_data)

    if len(parts) < 3:
        raise ValueError("Invalid S/MIME structure (could not split boundary)")

    raw_signed_content = parts[1]
    sig_part_raw = parts[2]

    sig_msg = email.message_from_bytes(sig_part_raw, policy=policy.default)

    # If the payload isn't base64 or qp, get_payload(decode=True) returns bytes or None
    decoded = sig_msg.get_payload(decode=True)
    if isinstance(decoded, bytes):
        binary_sig = decoded
    else:
        # Fallback if it's not base64 or quoted-printable
        raw_val = sig_msg.get_payload()
        binary_sig = raw_val.encode("utf-8") if isinstance(raw_val, str) else b""

    return raw_signed_content, binary_sig


def _inject_certificate_into_cms(binary_sig: bytes, cert_bytes: bytes) -> bytes:
    """
    Forces our trusted public certificate into the ASN.1 CMS bag.
    This guarantees verification succeeds even if the sender omitted their cert.
    """
    try:
        content_info = cms.ContentInfo.load(binary_sig)
        signed_data_cms = content_info["content"]

        c_bytes = cert_bytes if b"BEGIN" not in cert_bytes else pem.unarmor(cert_bytes)[2]
        parsed_cert = asn1_x509.Certificate.load(c_bytes)
        choice = cms.CertificateChoices(name="certificate", value=parsed_cert)

        if not signed_data_cms["certificates"]:
            signed_data_cms["certificates"] = [choice]
        else:
            existing_serials = [
                c.chosen.serial_number
                for c in signed_data_cms["certificates"]
                if c.name == "certificate"
            ]
            if parsed_cert.serial_number not in existing_serials:
                signed_data_cms["certificates"].append(choice)

        return cast(bytes, content_info.dump())
    except (ValueError, TypeError, KeyError, IndexError) as e:
        logger.debug("certificate_injection_into_cms_failed", error=str(e))
        return binary_sig


def _execute_endesive_verification(
    binary_sig: bytes, raw_signed_content: bytes, cert_bytes: bytes
) -> bool:
    """
    Executes the actual cryptographic verification using endesive.
    Safely captures stdout to suppress CA error noise and catches deprecation warnings.
    """

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=CryptographyDeprecationWarning)
        with contextlib.redirect_stdout(io.StringIO()):
            hashok, sigok, _certok = endesive.verifier.verify(
                binary_sig, raw_signed_content, [cert_bytes]
            )

    if not (hashok and sigok):
        raise ValueError(f"Hash Match: {hashok}, Signature Match: {sigok}")

    return True


def verify_signature(
    signed_data: bytes,
    public_cert_pem: str | bytes,
) -> tuple[bool, bytes]:
    """
    Verifies an S/MIME signature (multipart/signed) natively using endesive.
    Returns a tuple of (is_valid, verified_payload).
    """
    try:
        # 1. Extract bytes
        raw_signed_content, binary_sig = _extract_smime_signature_parts(signed_data)

        # 2. Prepare certificate
        cert_bytes = (
            public_cert_pem
            if isinstance(public_cert_pem, bytes)
            else public_cert_pem.encode("utf-8")
        )

        # 3. Inject certificate into ASN.1 structure to prevent crashes
        binary_sig = _inject_certificate_into_cms(binary_sig, cert_bytes)

        # 4. Mathematically verify
        is_valid = _execute_endesive_verification(binary_sig, raw_signed_content, cert_bytes)

        return is_valid, raw_signed_content
    except Exception as e:
        raise ValueError(f"Native Signature Verify Error: {e}") from e
