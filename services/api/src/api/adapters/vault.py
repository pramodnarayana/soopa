import os
import sys
import uuid

import hvac
import structlog

logger = structlog.get_logger(__name__)


class VaultAdapter:
    def __init__(self) -> None:
        self.url = os.getenv("VAULT_ADDR", "http://localhost:8200")
        token = os.getenv("VAULT_TOKEN")
        env = os.getenv("ENVIRONMENT", "production")
        if not token:
            if env in ("development", "dev", "test", "local") or "pytest" in sys.modules:
                token = "root"
            else:
                raise ValueError(
                    "VAULT_TOKEN environment variable is required in non-development environments."
                )

        self.token = token
        self.client = hvac.Client(url=self.url, token=self.token)
        self.mount_point = "secret"

        # Ensure secret engine is enabled in dev mode
        try:
            if not self.client.sys.is_initialized():
                logger.warning("Vault is not initialized.")
            else:
                engines = self.client.sys.list_mounted_secrets_engines()
                if f"{self.mount_point}/" not in engines:
                    self.client.sys.enable_secrets_engine(
                        backend_type="kv", path=self.mount_point, options={"version": "2"}
                    )
        except Exception as e:
            logger.error("vault_connection_failed", error=str(e))

    def store_private_key(self, private_key_pem: bytes, alias_prefix: str = "as2_key") -> str:
        """
        Stores a private key in Vault and returns the Vault reference path.
        """
        ref_id = str(uuid.uuid4())
        path = f"edi/{alias_prefix}/{ref_id}"

        self.client.secrets.kv.v2.create_or_update_secret(
            path=path,
            secret={"private_key_pem": private_key_pem.decode("utf-8")},
            mount_point=self.mount_point,
        )
        return path

    def retrieve_private_key(self, vault_ref: str) -> bytes:
        """
        Retrieves a private key from Vault.
        """
        read_response = self.client.secrets.kv.v2.read_secret_version(
            path=vault_ref, mount_point=self.mount_point
        )
        if not isinstance(read_response, dict):
            raise TypeError("Expected Vault response to be a dictionary")

        data = read_response.get("data", {})
        if not isinstance(data, dict):
            raise TypeError("Expected Vault 'data' to be a dictionary")

        inner_data = data.get("data", {})
        if not isinstance(inner_data, dict):
            raise TypeError("Expected Vault inner 'data' to be a dictionary")

        pem_str = inner_data.get("private_key_pem")
        if not isinstance(pem_str, str):
            raise TypeError("Expected private_key_pem to be a string")

        return pem_str.encode("utf-8")


# Singleton instance
vault = VaultAdapter()
