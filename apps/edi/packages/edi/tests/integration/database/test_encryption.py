import os
from unittest import mock

import pytest
from cryptography.fernet import Fernet, InvalidToken

from edi.adapters.outbound.database.encryption import DBEncryptionAdapter


@pytest.fixture
def adapter():
    return DBEncryptionAdapter()


def test_fernet_initialization_with_key(adapter):
    key = Fernet.generate_key().decode("utf-8")
    with mock.patch.dict(os.environ, {"DB_ENCRYPTION_KEY": key}):
        fernet = adapter.fernet
        assert fernet is not None
        assert adapter._initialized is True


def test_fernet_initialization_without_key(adapter):
    with mock.patch.dict(os.environ, {}, clear=True):
        fernet = adapter.fernet
        assert fernet is None
        assert adapter._initialized is False


def test_fernet_initialization_with_invalid_key(adapter):
    with (
        mock.patch.dict(os.environ, {"DB_ENCRYPTION_KEY": "invalid_key"}),
        pytest.raises(RuntimeError),
    ):
        _ = adapter.fernet


def test_encrypt_decrypt_success(adapter):
    key = Fernet.generate_key().decode("utf-8")
    with mock.patch.dict(os.environ, {"DB_ENCRYPTION_KEY": key}):
        # Trigger initialization
        assert adapter.fernet is not None
        original_data = "sensitive_secret"
        encrypted = adapter.encrypt(original_data)
        assert encrypted != original_data
        decrypted = adapter.decrypt(encrypted)
        assert decrypted == original_data


def test_encrypt_without_key_raises_error(adapter):
    with mock.patch.dict(os.environ, {}, clear=True):
        # Trigger initialization attempt
        _ = adapter.fernet
        with pytest.raises(RuntimeError, match="DB_ENCRYPTION_KEY not configured"):
            adapter.encrypt("data")


def test_decrypt_without_key_raises_error(adapter):
    with mock.patch.dict(os.environ, {}, clear=True):
        # Trigger initialization attempt
        _ = adapter.fernet
        with pytest.raises(RuntimeError, match="DB_ENCRYPTION_KEY not configured"):
            adapter.decrypt("token")


def test_decrypt_with_invalid_token(adapter):
    key = Fernet.generate_key().decode("utf-8")
    with mock.patch.dict(os.environ, {"DB_ENCRYPTION_KEY": key}):
        # Trigger initialization
        assert adapter.fernet is not None
        with pytest.raises(InvalidToken):
            adapter.decrypt("invalid_token_format")
