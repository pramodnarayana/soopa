"""Port protocol for cryptographic signatures and HMAC verification."""

from abc import abstractmethod
from typing import Protocol


class SignaturePort(Protocol):
    """Hexagonal outbound port for generating and validating cryptographic signatures."""

    @abstractmethod
    def sign(self, payload: bytes) -> str:
        """Generates a cryptographic signature (e.g. HMAC-SHA256 hex string)."""
        ...

    @abstractmethod
    def verify(self, payload: bytes, signature: str) -> bool:
        """Verifies a signature using constant-time comparison to prevent timing attacks."""
        ...
