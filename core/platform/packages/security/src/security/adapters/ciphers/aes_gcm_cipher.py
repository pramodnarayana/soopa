"""AES-256-GCM symmetric cipher for credential and field-level encryption."""

from __future__ import annotations

import base64
import json
import os
import re
from collections.abc import Mapping

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from security.ports.cipher_port import CipherPort
from security.types import JsonDict

_KEY_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,36}$")
_KID_HEADER_PREFIX = b"kid:"


class AesGcmCipher(CipherPort):
    """AES-256-GCM authenticated cipher implementation with optional key-versioned keyring rotation.

    Prepends a 12-byte cryptographically secure nonce to the ciphertext.
    - Unprefixed (default): `[nonce (12 bytes) + ciphertext + auth tag (16 bytes)]`.
    - Key-versioned (`key_id` set): `b"kid:<key_id>:" + [nonce (12 bytes) + ciphertext + auth tag (16 bytes)]`
      with `associated_data=key_id.encode("ascii")` bound to the GCM tag to prevent key-ID tampering.
    """

    def __init__(
        self,
        key: bytes,
        *,
        key_id: str | None = None,
        keyring: Mapping[str, bytes] | None = None,
    ) -> None:
        if len(key) != 32:
            raise ValueError(f"AES-256-GCM key must be exactly 32 bytes (got {len(key)})")
        if key_id is not None and not _KEY_ID_PATTERN.match(key_id):
            raise ValueError(f"Invalid key_id '{key_id}': must match {_KEY_ID_PATTERN.pattern}")
        self._key = key
        self._key_id = key_id
        self._aesgcm = AESGCM(self._key)
        self._keyring_ciphers: dict[str, AESGCM] = {}
        if key_id is not None:
            self._keyring_ciphers[key_id] = self._aesgcm
        if keyring:
            for kid, k_bytes in keyring.items():
                if not _KEY_ID_PATTERN.match(kid):
                    raise ValueError(f"Invalid keyring key_id '{kid}'")
                if len(k_bytes) != 32:
                    raise ValueError(f"Keyring key '{kid}' must be 32 bytes (got {len(k_bytes)})")
                self._keyring_ciphers[kid] = AESGCM(k_bytes)

    @property
    def key_id(self) -> str | None:
        return self._key_id

    @classmethod
    def generate_key(cls) -> bytes:
        """Generates a secure random 32-byte (256-bit) encryption key."""
        return AESGCM.generate_key(bit_length=256)

    def _encrypt_raw_bytes(self, plaintext: bytes) -> bytes:
        nonce = os.urandom(12)
        if self._key_id is not None:
            aad = self._key_id.encode("ascii")
            ciphertext = self._aesgcm.encrypt(nonce, plaintext, associated_data=aad)
            return _KID_HEADER_PREFIX + aad + b":" + nonce + ciphertext
        ciphertext = self._aesgcm.encrypt(nonce, plaintext, associated_data=None)
        return nonce + ciphertext

    def _try_decrypt_key_versioned(self, encrypted_bytes: bytes) -> bytes | None:
        if not encrypted_bytes.startswith(_KID_HEADER_PREFIX):
            return None
        rest = encrypted_bytes[len(_KID_HEADER_PREFIX) :]
        sep_idx = rest.find(b":")
        if sep_idx <= 0:
            return None
        try:
            kid = rest[:sep_idx].decode("ascii")
        except UnicodeDecodeError:
            return None
        if not _KEY_ID_PATTERN.match(kid):
            return None
        payload = rest[sep_idx + 1 :]
        if len(payload) < 28:
            raise ValueError("Ciphertext is too short to contain valid nonce and auth tag.")
        cipher = self._keyring_ciphers.get(kid)
        if cipher is None:
            raise ValueError(f"Unknown encryption key_id: '{kid}'")
        return cipher.decrypt(payload[:12], payload[12:], associated_data=kid.encode("ascii"))

    def _decrypt_raw_bytes(self, encrypted_bytes: bytes) -> bytes:
        versioned = self._try_decrypt_key_versioned(encrypted_bytes)
        if versioned is not None:
            return versioned

        if len(encrypted_bytes) < 28:
            raise ValueError("Ciphertext is too short to contain valid nonce and auth tag.")

        nonce = encrypted_bytes[:12]
        ciphertext = encrypted_bytes[12:]
        try:
            return self._aesgcm.decrypt(nonce, ciphertext, associated_data=None)
        except InvalidTag:
            for cipher in self._keyring_ciphers.values():
                if cipher is self._aesgcm:
                    continue
                try:
                    return cipher.decrypt(nonce, ciphertext, associated_data=None)
                except InvalidTag:
                    continue
            raise

    def encrypt(self, data: JsonDict) -> bytes:
        return self.encrypt_dict(data)

    def decrypt(self, encrypted_bytes: bytes) -> JsonDict:
        return self.decrypt_dict(encrypted_bytes)

    def encrypt_dict(self, data: JsonDict) -> bytes:
        """Serializes dictionary to JSON and encrypts with a 12-byte random nonce."""
        json_bytes = json.dumps(data, sort_keys=True).encode("utf-8")
        return self._encrypt_raw_bytes(json_bytes)

    def decrypt_dict(self, encrypted_bytes: bytes) -> JsonDict:
        """Verifies GCM auth tag and deserializes JSON dictionary."""
        decrypted_bytes = self._decrypt_raw_bytes(encrypted_bytes)
        parsed = json.loads(decrypted_bytes.decode("utf-8"))
        if not isinstance(parsed, dict):
            raise TypeError("Decrypted payload is not a dictionary.")
        return parsed

    def encrypt_str(self, text: str) -> str:
        """Encrypts plaintext string and returns standard base64 encoded ciphertext."""
        combined = self._encrypt_raw_bytes(text.encode("utf-8"))
        return base64.b64encode(combined).decode("ascii")

    def decrypt_str(self, ciphertext: str) -> str:
        """Decrypts base64 encoded ciphertext back to plaintext string."""
        raw_bytes = base64.b64decode(ciphertext.encode("ascii"))
        decrypted_bytes = self._decrypt_raw_bytes(raw_bytes)
        return decrypted_bytes.decode("utf-8")
