"""Unit tests for the centralized security package."""

import pytest
from security.adapters.ciphers.aes_gcm_cipher import AesGcmCipher
from security.adapters.ciphers.fernet_cipher import FernetCipher
from security.adapters.signatures.hmac_signer import HmacSigner
from security.provider import SecurityProvider
from security.sanitization.scrubber import sanitize_error
from security.testing.fakes.in_memory_vault import InMemoryVaultAdapter


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


@pytest.mark.asyncio
async def test_in_memory_vault_lifecycle() -> None:
    vault = InMemoryVaultAdapter()

    key_bytes = b"-----BEGIN RSA PRIVATE KEY-----\nMIIE...\n-----END RSA PRIVATE KEY-----"
    ref = await vault.store_private_key(key_bytes, category="as2_partner")
    assert ref.startswith("soopa/as2_partner/")

    retrieved = await vault.retrieve_secret(ref)
    assert retrieved == key_bytes

    await vault.delete_secret(ref)
    with pytest.raises(ValueError, match="Secret not found"):
        await vault.retrieve_secret(ref)


def test_security_provider_resolves_components() -> None:
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
