import os

from secret_store.adapters.aws_secrets_manager import AwsSecretsManagerAdapter
from secret_store.ports.secret_store_port import SecretStorePort


class SecretStoreProvider:
    @staticmethod
    def create() -> SecretStorePort:
        """
        Creates a SecretStorePort using platform environment variables.
        """
        # Read generic SECRETS_MOUNT_PATH or fallback to /mnt/secrets
        mount_path = os.getenv("SECRETS_MOUNT_PATH", "/mnt/secrets")

        return AwsSecretsManagerAdapter(secrets_mount_path=mount_path)
