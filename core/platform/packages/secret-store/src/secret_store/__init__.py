"""Centralized Enterprise Secret Store Package."""

from secret_store.adapters.aws_secrets_manager import (
    AwsSecretsManagerAdapter,
    SecretsManagerClientProtocol,
)
from secret_store.adapters.mounted_path_resolver import MountedSecretPathResolver
from secret_store.ports.secret_path_resolver_port import MountedSecretPathResolverPort
from secret_store.ports.secret_store_port import SecretStorePort
from secret_store.provider import SecretStoreBackend, SecretStoreProvider

__all__ = [
    "AwsSecretsManagerAdapter",
    "MountedSecretPathResolver",
    "MountedSecretPathResolverPort",
    "SecretStoreBackend",
    "SecretStorePort",
    "SecretStoreProvider",
    "SecretsManagerClientProtocol",
]
