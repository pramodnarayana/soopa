from typing import Protocol


class CertificateGeneratorPort(Protocol):
    """Port for generating self-signed X.509 certificate and private key pairs."""

    def generate_self_signed_cert(self, common_name: str) -> tuple[bytes, bytes]: ...
