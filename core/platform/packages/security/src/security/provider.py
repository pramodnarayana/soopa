import base64
import binascii
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

    @staticmethod
    def _is_ephemeral_allowed() -> bool:
        return os.getenv("ALLOW_EPHEMERAL_SECURITY_KEYS", "").lower() in ("true", "1")

    @classmethod
    def _decode_aes_key(cls, raw_key: str) -> bytes:
        """Decodes raw key string supporting 64-char hex, 44-char base64, or 32 raw bytes."""
        stripped = raw_key.strip()
        # 1. Hex encoding (64 hex characters = 32 bytes)
        if len(stripped) == 64:
            try:
                return bytes.fromhex(stripped)
            except ValueError as e:
                raise ValueError(f"Malformed 64-character hex encryption key: {e}") from e

        # 2. Base64 encoding (44 chars = 32 bytes)
        if len(stripped) == 44:
            try:
                decoded = base64.b64decode(stripped, validate=True)
                if len(decoded) == 32:
                    return decoded
                raise ValueError(
                    f"44-character base64 encryption key decoded to {len(decoded)} bytes; expected 32 bytes"
                )
            except (binascii.Error, ValueError) as e:
                raise ValueError(f"Malformed 44-character base64 encryption key: {e}") from e

        # 3. Raw 32 bytes UTF-8
        key_bytes = stripped.encode("utf-8")
        if len(key_bytes) == 32:
            return key_bytes

        # 4. Fallback: Derive deterministic 32-byte key via SHA-256
        return hashlib.sha256(key_bytes).digest()

    @classmethod
    def get_cipher(cls, key: bytes | None = None) -> CipherPort:
        """Resolves an AES-256-GCM CipherPort for authenticated envelope encryption.

        If key is not provided, reads SECURITY_AES_KEY or DB_ENCRYPTION_KEY from environment.
        Raises RuntimeError if neither key is set in production.
        """
        if key is None:
            raw_key = os.getenv("SECURITY_AES_KEY") or os.getenv("DB_ENCRYPTION_KEY")
            if not raw_key:
                if not cls._is_ephemeral_allowed():
                    raise RuntimeError(
                        "Neither SECURITY_AES_KEY nor DB_ENCRYPTION_KEY is configured in environment. "
                        "To enable ephemeral keys for local testing, set ALLOW_EPHEMERAL_SECURITY_KEYS=true."
                    )
                if cls._cached_ephemeral_key is None:
                    logger.warning(
                        "SECURITY_AES_KEY and DB_ENCRYPTION_KEY are unset. Generating ephemeral key."
                    )
                    cls._cached_ephemeral_key = AESGCM.generate_key(bit_length=256)
                key = cls._cached_ephemeral_key
            else:
                key = cls._decode_aes_key(raw_key)

        return AesGcmCipher(key=key)

    @classmethod
    def get_fernet_cipher(cls, key: str | None = None) -> CipherPort:
        """Resolves a Fernet CipherPort for backward compatibility with DB_ENCRYPTION_KEY.

        Raises RuntimeError if key is not provided and DB_ENCRYPTION_KEY is not set in production.
        """
        raw_key = key or os.getenv("DB_ENCRYPTION_KEY")
        if not raw_key:
            if not cls._is_ephemeral_allowed():
                raise RuntimeError(
                    "DB_ENCRYPTION_KEY is not configured in environment. "
                    "To enable ephemeral keys for local testing, set ALLOW_EPHEMERAL_SECURITY_KEYS=true."
                )
            raw_key = FernetCipher.generate_key()
        return FernetCipher(key=raw_key)

    @staticmethod
    def get_hmac_signer(secret: str | bytes) -> SignaturePort:
        """Resolves an HMAC-SHA256 SignaturePort for webhook verification."""
        return HmacSigner(secret=secret)
