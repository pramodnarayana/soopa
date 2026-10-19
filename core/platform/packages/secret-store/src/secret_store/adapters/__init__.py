"""Adapters for secret management."""

from secret_store.adapters.aws_secrets_manager import (
    AwsSecretsManagerAdapter,
    SecretsManagerClientProtocol,
)
from secret_store.adapters.mounted_path_resolver import MountedSecretPathResolver

__all__ = [
    "AwsSecretsManagerAdapter",
    "MountedSecretPathResolver",
    "SecretsManagerClientProtocol",
]
