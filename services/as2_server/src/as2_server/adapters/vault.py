import os


class EnvironmentVaultService:
    def get_host_private_key(self) -> bytes:
        """
        Load the host AS2 private key PEM from an environment variable.
        """
        key_pem = os.getenv("AS2_HOST_PRIVATE_KEY_PEM", "")
        return key_pem.encode("utf-8") if key_pem else b""

    def get_host_certificate(self) -> bytes:
        """
        Load the host AS2 public certificate PEM from an environment variable.
        """
        cert_pem = os.getenv("AS2_HOST_PUBLIC_CERT_PEM", "")
        return cert_pem.encode("utf-8") if cert_pem else b""
