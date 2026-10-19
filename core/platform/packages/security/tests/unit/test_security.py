import base64
import hashlib

import pytest
from security.adapters.ciphers.aes_gcm_cipher import AesGcmCipher
from security.adapters.ciphers.fernet_cipher import FernetCipher
from security.adapters.signatures.hmac_signer import HmacSigner
from security.provider import SecurityProvider
from security.sanitization.scrubber import sanitize_error


def test_aes_gcm_cipher_dict_and_str_roundtrip() -> None:
    key = AesGcmCipher.generate_key()
    cipher = AesGcmCipher(key)

    # Test dictionary encryption
    data = {"api_key": "sec_12345", "client_secret": "my_secret_token", "is_prod": True}
    encrypted = cipher.encrypt_dict(data)
    assert isinstance(encrypted, bytes)
    assert b"sec_12345" not in encrypted
    decrypted = cipher.decrypt_dict(encrypted)
    assert decrypted == data

    # Test string encryption
    text = "sftp_secret_password"
    enc_str = cipher.encrypt_str(text)
    assert isinstance(enc_str, str)
    assert text not in enc_str
    dec_str = cipher.decrypt_str(enc_str)
    assert dec_str == text


def test_fernet_cipher_dict_and_str_roundtrip() -> None:
    key = FernetCipher.generate_key()
    cipher = FernetCipher(key)

    data = {"token": "secret_abc"}
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


def test_security_provider_resolves_components(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALLOW_EPHEMERAL_SECURITY_KEYS", "true")
    cipher = SecurityProvider.get_cipher()
    assert cipher is not None

    fernet = SecurityProvider.get_fernet_cipher()
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

    # Non-ASCII unicode characters
    assert signer.verify(payload, "invalid_sig_\U0001f525") is False
    assert signer.verify(payload, "\xe9\xe8\xea\xeb") is False
    assert signer.verify(payload, "") is False


def test_security_provider_decodes_hex_and_base64_keys() -> None:
    # 32-byte key in hex (64 chars)
    raw_bytes = b"0123456789abcdef0123456789abcdef"
    hex_key = raw_bytes.hex()
    assert len(hex_key) == 64
    cipher_hex = SecurityProvider.get_cipher(key=SecurityProvider._decode_aes_key(hex_key))
    assert cipher_hex.decrypt_str(cipher_hex.encrypt_str("hello")) == "hello"

    # 32-byte key in base64 (44 chars)
    b64_key = base64.b64encode(raw_bytes).decode("ascii")
    assert len(b64_key) == 44
    cipher_b64 = SecurityProvider.get_cipher(key=SecurityProvider._decode_aes_key(b64_key))
    assert cipher_b64.decrypt_str(cipher_b64.encrypt_str("hello")) == "hello"

    # Malformed 64-char hex key raises ValueError
    malformed_hex = "g" * 64
    with pytest.raises(ValueError, match="Malformed 64-character hex encryption key"):
        SecurityProvider._decode_aes_key(malformed_hex)

    # Malformed 44-char base64 key raises ValueError
    malformed_b64 = "????" + ("a" * 40)
    with pytest.raises(ValueError, match="Malformed 44-character base64 encryption key"):
        SecurityProvider._decode_aes_key(malformed_b64)

    # 44-char base64 key that decodes to non-32 bytes raises ValueError
    non_32_b64 = base64.b64encode(b"a" * 33).decode("ascii")
    assert len(non_32_b64) == 44
    with pytest.raises(ValueError, match="decoded to 33 bytes; expected 32 bytes"):
        SecurityProvider._decode_aes_key(non_32_b64)

    # Legacy arbitrary passphrase falls back to SHA-256 derivation
    derived = SecurityProvider._decode_aes_key("legacy-arbitrary-password")
    assert len(derived) == 32
    assert derived == hashlib.sha256(b"legacy-arbitrary-password").digest()


def test_security_provider_fails_fast_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("SECURITY_AES_KEY", raising=False)
    monkeypatch.delenv("DB_ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("ALLOW_EPHEMERAL_SECURITY_KEYS", raising=False)

    with pytest.raises(RuntimeError, match="Neither SECURITY_AES_KEY nor DB_ENCRYPTION_KEY"):
        SecurityProvider.get_cipher()

    with pytest.raises(RuntimeError, match="DB_ENCRYPTION_KEY is not configured"):
        SecurityProvider.get_fernet_cipher()
