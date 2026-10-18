import hashlib
import os

import structlog
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from security.adapters.ciphers.aes_gcm_cipher import AesGcmCipher
from security.adapters.ciphers.fernet_cipher import FernetCipher
from security.adapters.secrets.aws_secrets_manager import AwsSecretsManagerAdapter
from security.adapters.signatures.hmac_signer import HmacSigner
from security.ports.cipher_port import CipherPort
from security.ports.secret_store_port import SecretStorePort
from security.ports.signature_port import SignaturePort

logger = structlog.get_logger(__name__)


class SecurityProvider:
    """Centralized enterprise provider for platform security capabilities."""

    _cached_ephemeral_key: bytes | None = None

    @classmethod
    def get_secret_store(cls, secrets_mount_path: str | None = None) -> SecretStorePort:
        mount_path: str = secrets_mount_path or os.getenv("SECRETS_MOUNT_PATH") or "/mnt/secrets"
        return AwsSecretsManagerAdapter(secrets_mount_path=mount_path)

    @classmethod
    def get_cipher(cls, key: bytes | None = None) -> CipherPort:
        """Resolves an AES-256-GCM CipherPort for authenticated envelope encryption.

        If key is not provided, reads SECURITY_AES_KEY or DB_ENCRYPTION_KEY from environment.
        """
        if key is None:
            raw_key = os.getenv("SECURITY_AES_KEY") or os.getenv("DB_ENCRYPTION_KEY")
            if not raw_key:
                if cls._cached_ephemeral_key is None:
                    logger.warning(
                        "SECURITY_AES_KEY and DB_ENCRYPTION_KEY are unset. Generating ephemeral key."
                    )
                    cls._cached_ephemeral_key = AESGCM.generate_key(bit_length=256)
                key = cls._cached_ephemeral_key
            else:
                # If key is 32 raw bytes (or hex/base64 encoded 32 bytes)
                key_bytes = raw_key.encode("utf-8")
                key = key_bytes if len(key_bytes) == 32 else hashlib.sha256(key_bytes).digest()

        return AesGcmCipher(key=key)

    @staticmethod
    def get_fernet_cipher(key: str | None = None) -> CipherPort:
        """Resolves a Fernet CipherPort for backward compatibility with DB_ENCRYPTION_KEY."""
        raw_key = key or os.getenv("DB_ENCRYPTION_KEY")
        if not raw_key:
            raw_key = FernetCipher.generate_key()
        return FernetCipher(key=raw_key)

    @staticmethod
    def get_hmac_signer(secret: str | bytes) -> SignaturePort:
        """Resolves an HMAC-SHA256 SignaturePort for webhook verification."""
        return HmacSigner(secret=secret)
