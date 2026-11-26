"""Centralized Enterprise Secret Store Package."""

from secret_store.adapters.aws_secrets_manager import (
    AwsSecretsManagerAdapter,
    SecretsManagerClientProtocol,
)
from secret_store.adapters.file_system_secret_store import (
    atomic_write_secure_file,
    ensure_secure_directory,
)
from secret_store.adapters.mounted_path_resolver import MountedSecretPathResolver
from secret_store.config import DEFAULT_SECRETS_MOUNT_PATH, PlatformSecretStoreSettings
from secret_store.domain.enums import SecretStoreBackend
from secret_store.ports.secret_path_resolver_port import MountedSecretPathResolverPort
from secret_store.ports.secret_store_port import SecretStorePort
from secret_store.provider import SecretStoreProvider

__all__ = [
    "DEFAULT_SECRETS_MOUNT_PATH",
    "AwsSecretsManagerAdapter",
    "MountedSecretPathResolver",
    "MountedSecretPathResolverPort",
    "PlatformSecretStoreSettings",
    "SecretStoreBackend",
    "SecretStorePort",
    "SecretStoreProvider",
    "SecretsManagerClientProtocol",
    "atomic_write_secure_file",
    "ensure_secure_directory",
]
