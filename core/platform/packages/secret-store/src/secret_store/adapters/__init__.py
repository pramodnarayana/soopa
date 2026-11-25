"""Secret store adapters."""

from secret_store.adapters.aws_secrets_manager import (
    AwsSecretsManagerAdapter,
    SecretsManagerClientProtocol,
)
from secret_store.adapters.file_system_secret_store import FileSystemSecretStoreAdapter
from secret_store.adapters.mounted_path_resolver import MountedSecretPathResolver
from secret_store.adapters.vault_secret_store import VaultSecretStoreAdapter

__all__ = [
    "AwsSecretsManagerAdapter",
    "FileSystemSecretStoreAdapter",
    "MountedSecretPathResolver",
    "SecretsManagerClientProtocol",
    "VaultSecretStoreAdapter",
]
