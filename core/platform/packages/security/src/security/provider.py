import base64
import binascii
import hashlib
import os
from collections.abc import Mapping

import structlog

from security.adapters.ciphers.aes_gcm_cipher import AesGcmCipher
from security.adapters.ciphers.fernet_cipher import FernetCipher
from security.adapters.signatures.hmac_signer import HmacSigner
from security.ports.cipher_port import CipherPort
from security.ports.signature_port import SignaturePort

logger = structlog.get_logger(__name__)

_EPHEMERAL_DEV_SEED = b"soopa-ephemeral-dev-aes-256-gcm-key"


class SecurityProvider:
    """Centralized enterprise provider for platform cryptography capabilities."""

    @staticmethod
    def _is_ephemeral_allowed(env: Mapping[str, str] | None = None) -> bool:
        source = os.environ if env is None else env
        env_name = (source.get("ENVIRONMENT") or source.get("APP_ENV") or "").lower()
        if env_name == "production":
            return False
        return source.get("ALLOW_EPHEMERAL_SECURITY_KEYS", "").lower() in ("true", "1")

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
    def _parse_keyring_env(cls, raw_keyring: str | None) -> dict[str, bytes]:
        """Parses comma-separated '<key_id>:<raw_key>' pairs from SECURITY_AES_KEYRING."""
        if not raw_keyring or not raw_keyring.strip():
            return {}
        parsed: dict[str, bytes] = {}
        for entry in raw_keyring.split(","):
            item = entry.strip()
            if not item:
                continue
            if ":" not in item:
                raise ValueError(
                    f"Malformed SECURITY_AES_KEYRING entry '{item}': expected '<key_id>:<key>'"
                )
            kid, raw_key = item.split(":", 1)
            parsed[kid.strip()] = cls._decode_aes_key(raw_key)
        return parsed

    @classmethod
    def get_cipher(
        cls,
        key: bytes | None = None,
        *,
        key_id: str | None = None,
        keyring: Mapping[str, bytes] | None = None,
        env: Mapping[str, str] | None = None,
    ) -> CipherPort:
        """Resolves an AES-256-GCM CipherPort for authenticated envelope encryption.

        If key is not provided, reads SECURITY_AES_KEY or DB_ENCRYPTION_KEY from environment.
        Optionally reads SECURITY_AES_KEY_ID and SECURITY_AES_KEYRING for zero-downtime key rotation.
        Raises RuntimeError if neither key is set in production.
        """
        source = os.environ if env is None else env
        if key is None:
            raw_key = source.get("SECURITY_AES_KEY") or source.get("DB_ENCRYPTION_KEY")
            if not raw_key:
                env_name = (source.get("ENVIRONMENT") or source.get("APP_ENV") or "").lower()
                if env_name == "production":
                    raise RuntimeError(
                        "Neither SECURITY_AES_KEY nor DB_ENCRYPTION_KEY is configured in production environment."
                    )
                if not cls._is_ephemeral_allowed(source):
                    raise RuntimeError(
                        "Neither SECURITY_AES_KEY nor DB_ENCRYPTION_KEY is configured in environment. "
                        "To enable ephemeral keys for local testing, set ALLOW_EPHEMERAL_SECURITY_KEYS=true."
                    )
                logger.warning("ephemeral_security_key_derived")
                key = hashlib.sha256(_EPHEMERAL_DEV_SEED).digest()
            else:
                key = cls._decode_aes_key(raw_key)

        resolved_key_id = (
            key_id if key_id is not None else (source.get("SECURITY_AES_KEY_ID") or None)
        )
        resolved_keyring = (
            keyring
            if keyring is not None
            else cls._parse_keyring_env(source.get("SECURITY_AES_KEYRING"))
        )

        return AesGcmCipher(key=key, key_id=resolved_key_id, keyring=resolved_keyring)

    @classmethod
    def get_fernet_cipher(
        cls,
        key: str | None = None,
        *,
        env: Mapping[str, str] | None = None,
    ) -> CipherPort:
        """Resolves a Fernet CipherPort for backward compatibility with DB_ENCRYPTION_KEY.

        Raises RuntimeError if key is not provided and DB_ENCRYPTION_KEY is not set in production.
        """
        source = os.environ if env is None else env
        raw_key = key or source.get("DB_ENCRYPTION_KEY")
        if not raw_key:
            if not cls._is_ephemeral_allowed(source):
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
