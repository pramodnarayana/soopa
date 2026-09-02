"""
SmimeCryptoService — Concrete implementation of CryptoServicePort.

Delegates to the existing smime.py low-level functions, wrapping them in a
class that satisfies the CryptoServicePort Protocol. This adapter is the ONLY
place in the codebase permitted to import from edi.adapters.outbound.security.smime.
"""

import structlog

from edi.adapters.outbound.security.smime import decrypt_payload, sign_payload, verify_signature
from edi.ports.outbound.crypto_service_port import CryptoServicePort

logger = structlog.get_logger(__name__)


class SmimeCryptoService:
    """
    S/MIME implementation of CryptoServicePort.

    Wraps the low-level smime.py functions with a proper class interface so
    the Application Layer can depend on the port abstraction rather than the
    concrete cryptography library.
    """

    def decrypt(
        self,
        encrypted_data: bytes,
        private_key_pem: bytes,
        public_cert_pem: bytes,
    ) -> bytes:
        """
        Decrypts an S/MIME enveloped-data payload.
        Falls back to header-prepend strategy on initial parse failure.
        """
        try:
            result = decrypt_payload(
                encrypted_data,
                private_key_pem=private_key_pem,
                public_cert_pem=public_cert_pem,
            )
            if result:
                return result
        except Exception as exc:  # noqa: BLE001
            logger.debug("smime_decrypt_initial_attempt_failed", error=str(exc))

        raise ValueError(
            "Decryption failed: no fallback available at service level. "
            "Caller must apply header reconstruction before retrying."
        )

    def verify_signature(
        self,
        data: bytes,
        public_cert_pem: bytes,
    ) -> tuple[bool, bytes]:
        """Verifies an S/MIME detached signature and returns the signed content."""
        return verify_signature(data, public_cert_pem=public_cert_pem)

    def sign(
        self,
        payload: bytes,
        private_key_pem: bytes,
        public_cert_pem: bytes,
        algorithm: str = "sha256",
    ) -> bytes:
        """Signs a payload using S/MIME / PKCS#7."""
        return sign_payload(
            payload,
            private_key_pem=private_key_pem,
            public_cert_pem=public_cert_pem,
            algorithm=algorithm,
        )


# Satisfy the port at import time (structural check)
_: CryptoServicePort = SmimeCryptoService()
