"""Fernet symmetric cipher for backward compatibility with DB_ENCRYPTION_KEY."""

import json

from cryptography.fernet import Fernet

from security.ports.cipher_port import CipherPort
from security.types import JsonDict


class FernetCipher(CipherPort):
    """Fernet symmetric cipher adapter (AES-128-CBC + HMAC-SHA256)."""

    def __init__(self, key: str | bytes) -> None:
        key_bytes = key.encode("utf-8") if isinstance(key, str) else key
        self._fernet = Fernet(key_bytes)

    @classmethod
    def generate_key(cls) -> str:
        """Generates a URL-safe base64-encoded 32-byte Fernet key."""
        return Fernet.generate_key().decode("ascii")

    def encrypt_str(self, text: str) -> str:
        return self._fernet.encrypt(text.encode("utf-8")).decode("utf-8")

    def decrypt_str(self, ciphertext: str) -> str:
        return self._fernet.decrypt(ciphertext.encode("utf-8")).decode("utf-8")

    def encrypt_dict(self, data: JsonDict) -> bytes:
        json_bytes = json.dumps(data, sort_keys=True).encode("utf-8")
        return self._fernet.encrypt(json_bytes)

    def decrypt_dict(self, encrypted_bytes: bytes) -> JsonDict:
        decrypted = self._fernet.decrypt(encrypted_bytes)
        parsed = json.loads(decrypted.decode("utf-8"))
        if not isinstance(parsed, dict):
            raise TypeError("Decrypted payload is not a dictionary.")
        return parsed
