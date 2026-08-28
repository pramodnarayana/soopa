"""
CryptoServicePort — Port for AS2 cryptographic operations.

Defines the outbound port that the Application Layer uses for S/MIME operations.
The concrete implementation (SmimeCryptoService) lives in edi.adapters.outbound.security
and is injected via the DI container, keeping the domain fully decoupled from
the cryptography library.
"""

from typing import Protocol, runtime_checkable


@runtime_checkable
class CryptoServicePort(Protocol):
    """
    Port for AS2 S/MIME cryptographic operations.

    The application layer depends on this abstraction — never on the concrete
    smime adapter directly.
    """

    def decrypt(
        self,
        encrypted_data: bytes,
        private_key_pem: bytes,
        public_cert_pem: bytes,
    ) -> bytes:
        """
        Decrypts an S/MIME enveloped-data payload.

        Raises:
            ValueError: If decryption fails after all fallbacks are exhausted.
        """
        ...

    def verify_signature(
        self,
        data: bytes,
        public_cert_pem: bytes,
    ) -> tuple[bool, bytes]:
        """
        Verifies an S/MIME signature and extracts the signed content.

        Returns:
            (is_valid, signed_payload_bytes)

        Raises:
            ValueError: If verification fails due to a malformed payload.
        """
        ...

    def sign(
        self,
        payload: bytes,
        private_key_pem: bytes,
        public_cert_pem: bytes,
        algorithm: str = "sha256",
    ) -> bytes:
        """
        Signs a payload using S/MIME / PKCS#7.

        Returns:
            Signed MIME bytes (multipart/signed envelope).
        """
        ...
