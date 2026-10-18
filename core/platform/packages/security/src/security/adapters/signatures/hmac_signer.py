"""HMAC-SHA256 signature generator and constant-time verifier."""

import hashlib
import hmac

from security.ports.signature_port import SignaturePort


class HmacSigner(SignaturePort):
    """HMAC-SHA256 signer with constant-time verification against timing attacks."""

    def __init__(self, secret: str | bytes) -> None:
        self._secret = secret.encode("utf-8") if isinstance(secret, str) else secret

    def sign(self, payload: bytes) -> str:
        """Computes HMAC-SHA256 hex digest for the payload."""
        return hmac.new(self._secret, payload, hashlib.sha256).hexdigest()

    def verify(self, payload: bytes, signature: str) -> bool:
        """Constant-time verification of signature."""
        expected = self.sign(payload)
        return hmac.compare_digest(expected, signature)
