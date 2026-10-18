"""AES-256-GCM symmetric cipher for credential and field-level encryption."""

import base64
import json
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from security.ports.cipher_port import CipherPort
from security.types import JsonDict


class AesGcmCipher(CipherPort):
    """AES-256-GCM authenticated cipher implementation.

    Prepends a 12-byte cryptographically secure nonce to the ciphertext.
    Output format: [nonce (12 bytes) + ciphertext + auth tag (16 bytes)].
    """

    def __init__(self, key: bytes) -> None:
        if len(key) != 32:
            raise ValueError(f"AES-256-GCM key must be exactly 32 bytes (got {len(key)})")
        self._key = key
        self._aesgcm = AESGCM(self._key)

    @classmethod
    def generate_key(cls) -> bytes:
        """Generates a secure random 32-byte (256-bit) encryption key."""
        return AESGCM.generate_key(bit_length=256)

    def encrypt(self, data: JsonDict) -> bytes:
        return self.encrypt_dict(data)

    def decrypt(self, encrypted_bytes: bytes) -> JsonDict:
        return self.decrypt_dict(encrypted_bytes)

    def encrypt_dict(self, data: JsonDict) -> bytes:
        """Serializes dictionary to JSON and encrypts with a 12-byte random nonce."""
        json_bytes = json.dumps(data, sort_keys=True).encode("utf-8")
        nonce = os.urandom(12)
        ciphertext = self._aesgcm.encrypt(nonce, json_bytes, associated_data=None)
        return nonce + ciphertext

    def decrypt_dict(self, encrypted_bytes: bytes) -> JsonDict:
        """Verifies GCM auth tag and deserializes JSON dictionary."""
        if len(encrypted_bytes) < 28:
            raise ValueError("Ciphertext is too short to contain valid nonce and auth tag.")

        nonce = encrypted_bytes[:12]
        ciphertext = encrypted_bytes[12:]
        decrypted_bytes = self._aesgcm.decrypt(nonce, ciphertext, associated_data=None)
        parsed = json.loads(decrypted_bytes.decode("utf-8"))
        if not isinstance(parsed, dict):
            raise TypeError("Decrypted payload is not a dictionary.")
        return parsed

    def encrypt_str(self, text: str) -> str:
        """Encrypts plaintext string and returns standard base64 encoded ciphertext."""
        data_bytes = text.encode("utf-8")
        nonce = os.urandom(12)
        ciphertext = self._aesgcm.encrypt(nonce, data_bytes, associated_data=None)
        combined = nonce + ciphertext
        return base64.b64encode(combined).decode("ascii")

    def decrypt_str(self, ciphertext: str) -> str:
        """Decrypts base64 encoded ciphertext back to plaintext string."""
        raw_bytes = base64.b64decode(ciphertext.encode("ascii"))
        if len(raw_bytes) < 28:
            raise ValueError("Ciphertext is too short to contain valid nonce and auth tag.")

        nonce = raw_bytes[:12]
        enc_payload = raw_bytes[12:]
        decrypted_bytes = self._aesgcm.decrypt(nonce, enc_payload, associated_data=None)
        return decrypted_bytes.decode("utf-8")
