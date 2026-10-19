"""Port protocol for symmetric encryption of sensitive database fields and credentials."""

from abc import abstractmethod
from typing import Protocol

from security.types import JsonDict


class CipherPort(Protocol):
    """Hexagonal outbound port for symmetric encryption at rest."""

    @abstractmethod
    def encrypt_str(self, text: str) -> str:
        """Encrypts a plaintext string into a base64 or safe ciphertext string."""
        ...

    @abstractmethod
    def decrypt_str(self, ciphertext: str) -> str:
        """Decrypts a ciphertext string back into plaintext."""
        ...

    @abstractmethod
    def encrypt_dict(self, data: JsonDict) -> bytes:
        """Encrypts a structured dictionary into an authenticated byte string."""
        ...

    @abstractmethod
    def decrypt_dict(self, encrypted_bytes: bytes) -> JsonDict:
        """Decrypts an authenticated byte string back into a structured dictionary."""
        ...

    def encrypt(self, data: JsonDict) -> bytes:
        """Convenience method alias for encrypt_dict."""
        return self.encrypt_dict(data)

    def decrypt(self, encrypted_bytes: bytes) -> JsonDict:
        """Convenience method alias for decrypt_dict."""
        return self.decrypt_dict(encrypted_bytes)
