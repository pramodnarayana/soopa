"""Zero-mock, zero-monkeypatch unit tests for platform security cryptography, key rotation, and scrubbing."""

import base64
import hashlib

import pytest
from cryptography.exceptions import InvalidTag
from security.adapters.ciphers.aes_gcm_cipher import AesGcmCipher
from security.adapters.ciphers.fernet_cipher import FernetCipher
from security.adapters.signatures.hmac_signer import HmacSigner
from security.provider import SecurityProvider
from security.sanitization.scrubber import sanitize_error
from security.types import JsonDict


def test_aes_gcm_cipher_dict_and_str_roundtrip() -> None:
    key = AesGcmCipher.generate_key()
    cipher = AesGcmCipher(key)

    data: JsonDict = {
        "api_key": "sec_12345",
        "client_secret": "my_secret_token",
        "is_prod": True,
    }
    encrypted = cipher.encrypt_dict(data)
    assert isinstance(encrypted, bytes)
    assert b"sec_12345" not in encrypted
    decrypted = cipher.decrypt_dict(encrypted)
    assert decrypted == data

    text = "sftp_secret_password"
    enc_str = cipher.encrypt_str(text)
    assert isinstance(enc_str, str)
    assert text not in enc_str
    dec_str = cipher.decrypt_str(enc_str)
    assert dec_str == text


def test_fernet_cipher_dict_and_str_roundtrip() -> None:
    key = FernetCipher.generate_key()
    cipher = FernetCipher(key)

    data: JsonDict = {"token": "secret_abc"}
    enc = cipher.encrypt_dict(data)
    dec = cipher.decrypt_dict(enc)
    assert dec == data

    text = "plain_password"
    enc_str = cipher.encrypt_str(text)
    dec_str = cipher.decrypt_str(enc_str)
    assert dec_str == text


def test_hmac_signer_verification() -> None:
    secret = "webhook_shared_secret"
    signer = HmacSigner(secret)

    payload = b'{"event":"meter.reading","kwh":42.5}'
    signature = signer.sign(payload)
    assert isinstance(signature, str)
    assert len(signature) == 64  # SHA256 hex digest

    assert signer.verify(payload, signature) is True
    assert signer.verify(payload + b"_tampered", signature) is False
    assert signer.verify(payload, "invalid_signature") is False


def test_security_provider_resolves_components() -> None:
    ephemeral_env = {"ALLOW_EPHEMERAL_SECURITY_KEYS": "true"}
    cipher = SecurityProvider.get_cipher(env=ephemeral_env)
    assert cipher is not None

    fernet = SecurityProvider.get_fernet_cipher(env=ephemeral_env)
    assert fernet is not None

    signer = SecurityProvider.get_hmac_signer("secret")
    assert signer is not None


def test_sanitization_scrubber_masks_sensitive_data() -> None:
    error_with_url_pass = "Failed connecting to https://user:secret123@sftp.utility.com:22"
    sanitized = sanitize_error(error_with_url_pass)
    assert "secret123" not in sanitized
    assert "https://[REDACTED]@sftp.utility.com:22" in sanitized

    error_with_bearer = "Unauthorized call: Bearer my_super_secret_token_12345"
    sanitized_bearer = sanitize_error(error_with_bearer)
    assert "my_super_secret_token_12345" not in sanitized_bearer
    assert "Bearer [REDACTED]" in sanitized_bearer


def test_hmac_signer_non_ascii_and_malformed_signatures() -> None:
    signer = HmacSigner("test_secret")
    payload = b"payload_bytes"

    assert signer.verify(payload, "invalid_sig_\U0001f525") is False
    assert signer.verify(payload, "\xe9\xe8\xea\xeb") is False
    assert signer.verify(payload, "") is False


def test_security_provider_decodes_hex_and_base64_keys() -> None:
    raw_bytes = b"0123456789abcdef0123456789abcdef"
    hex_key = raw_bytes.hex()
    assert len(hex_key) == 64
    cipher_hex = SecurityProvider.get_cipher(key=SecurityProvider._decode_aes_key(hex_key))
    assert cipher_hex.decrypt_str(cipher_hex.encrypt_str("hello")) == "hello"

    b64_key = base64.b64encode(raw_bytes).decode("ascii")
    assert len(b64_key) == 44
    cipher_b64 = SecurityProvider.get_cipher(key=SecurityProvider._decode_aes_key(b64_key))
    assert cipher_b64.decrypt_str(cipher_b64.encrypt_str("hello")) == "hello"

    malformed_hex = "g" * 64
    with pytest.raises(ValueError, match="Malformed 64-character hex encryption key"):
        SecurityProvider._decode_aes_key(malformed_hex)

    malformed_b64 = "????" + ("a" * 40)
    with pytest.raises(ValueError, match="Malformed 44-character base64 encryption key"):
        SecurityProvider._decode_aes_key(malformed_b64)

    non_32_b64 = base64.b64encode(b"a" * 33).decode("ascii")
    assert len(non_32_b64) == 44
    with pytest.raises(ValueError, match="decoded to 33 bytes; expected 32 bytes"):
        SecurityProvider._decode_aes_key(non_32_b64)

    derived = SecurityProvider._decode_aes_key("legacy-arbitrary-password")
    assert len(derived) == 32
    assert derived == hashlib.sha256(b"legacy-arbitrary-password").digest()


def test_security_provider_fails_fast_in_production() -> None:
    prod_env = {"ENVIRONMENT": "production"}

    with pytest.raises(RuntimeError, match="Neither SECURITY_AES_KEY nor DB_ENCRYPTION_KEY"):
        SecurityProvider.get_cipher(env=prod_env)

    with pytest.raises(RuntimeError, match="DB_ENCRYPTION_KEY is not configured"):
        SecurityProvider.get_fernet_cipher(env=prod_env)


def test_aes_gcm_cipher_key_versioned_rotation_and_aad_integrity() -> None:
    key_v1 = AesGcmCipher.generate_key()
    key_v2 = AesGcmCipher.generate_key()

    # 1. Encrypt under legacy unprefixed cipher (v1)
    cipher_legacy = AesGcmCipher(key_v1)
    legacy_ciphertext = cipher_legacy.encrypt_dict({"secret": "legacy_val"})

    # 2. Encrypt under key-versioned cipher v1
    cipher_v1 = AesGcmCipher(key_v1, key_id="k1")
    v1_ciphertext = cipher_v1.encrypt_dict({"secret": "v1_val"})
    assert v1_ciphertext.startswith(b"kid:k1:")

    # 3. Rotate to v2 while keeping v1 in keyring
    cipher_v2 = AesGcmCipher(key_v2, key_id="k2", keyring={"k1": key_v1})
    v2_ciphertext = cipher_v2.encrypt_dict({"secret": "v2_val"})
    assert v2_ciphertext.startswith(b"kid:k2:")

    # Zero-downtime rotation: cipher_v2 decrypts v2, v1 (prefixed), AND legacy (unprefixed)
    assert cipher_v2.decrypt_dict(v2_ciphertext) == {"secret": "v2_val"}
    assert cipher_v2.decrypt_dict(v1_ciphertext) == {"secret": "v1_val"}
    assert cipher_v2.decrypt_dict(legacy_ciphertext) == {"secret": "legacy_val"}

    # 4. AAD Tamper Detection: swapping header kid:k1: to kid:k2: fails GCM authentication
    tampered = b"kid:k2:" + v1_ciphertext[len(b"kid:k1:") :]
    with pytest.raises(InvalidTag):
        cipher_v2.decrypt_dict(tampered)

    # 5. SecurityProvider env resolution for SECURITY_AES_KEY_ID and SECURITY_AES_KEYRING
    provider_cipher = SecurityProvider.get_cipher(
        env={
            "SECURITY_AES_KEY": key_v2.hex(),
            "SECURITY_AES_KEY_ID": "k2",
            "SECURITY_AES_KEYRING": f"k1:{key_v1.hex()}",
        }
    )
    assert provider_cipher.decrypt_dict(v1_ciphertext) == {"secret": "v1_val"}
    assert provider_cipher.decrypt_dict(v2_ciphertext) == {"secret": "v2_val"}
