"""Centralized enterprise provider for platform secret store capabilities."""

from __future__ import annotations

import os
from collections.abc import Callable

import structlog
from seedwork.infra.config_models import PlatformAwsSettings

from secret_store.adapters.aws_secrets_manager import (
    AwsSecretsManagerAdapter,
    SecretsManagerClientProtocol,
)
from secret_store.adapters.file_system_secret_store import FileSystemSecretStoreAdapter
from secret_store.adapters.mounted_path_resolver import MountedSecretPathResolver
from secret_store.adapters.vault_secret_store import VaultSecretStoreAdapter
from secret_store.config import (
    DEFAULT_SECRETS_MOUNT_PATH,
    DEFAULT_VAULT_MOUNT_POINT,
    PlatformSecretStoreSettings,
)
from secret_store.domain.enums import SecretStoreBackend
from secret_store.ports.secret_path_resolver_port import MountedSecretPathResolverPort
from secret_store.ports.secret_store_port import SecretStorePort

logger = structlog.get_logger(__name__)


class SecretStoreProvider:
    """Centralized enterprise provider for platform secret management."""

    _secret_store_registry: dict[SecretStoreBackend, Callable[..., SecretStorePort]] = {}

    @classmethod
    def register_secret_store_backend(
        cls,
        backend: SecretStoreBackend | str,
        factory: Callable[..., SecretStorePort],
    ) -> None:
        """Registers a factory for a SecretStorePort implementation."""
        key = (
            backend
            if isinstance(backend, SecretStoreBackend)
            else SecretStoreBackend(str(backend).lower())
        )
        cls._secret_store_registry[key] = factory

    @classmethod
    def reset_registry(cls) -> None:
        """Resets the registered backend factories (used for clean teardown and test isolation)."""
        cls._secret_store_registry.clear()

    @classmethod
    def from_settings(
        cls,
        settings: PlatformSecretStoreSettings,
        *,
        aws_settings: PlatformAwsSettings | None = None,
        path_resolver: MountedSecretPathResolverPort | None = None,
        client: SecretsManagerClientProtocol | None = None,
    ) -> SecretStorePort:
        """Builds a SecretStorePort from validated ``PlatformSecretStoreSettings`` with fail-fast checks."""
        resolved_aws = aws_settings
        if settings.backend == SecretStoreBackend.AWS and client is None:
            resolved_aws = aws_settings or PlatformAwsSettings()
            settings.validate_against_aws(resolved_aws)

        return cls.get_secret_store(
            secrets_mount_path=settings.mount_path,
            backend=settings.backend,
            path_resolver=path_resolver,
            client=client,
            secrets_prefix=settings.prefix,
            aws_settings=resolved_aws,
            vault_url=settings.vault_url,
            vault_token=settings.vault_token,
            vault_mount_point=settings.vault_mount_point,
        )

    @classmethod
    def get_secret_store(
        cls,
        secrets_mount_path: str | None = None,
        backend: SecretStoreBackend | str | None = None,
        path_resolver: MountedSecretPathResolverPort | None = None,
        endpoint_url: str | None = None,
        region_name: str | None = None,
        client: SecretsManagerClientProtocol | None = None,
        aws_access_key_id: str | None = None,
        aws_secret_access_key: str | None = None,
        secrets_prefix: str | None = None,
        aws_settings: PlatformAwsSettings | None = None,
        vault_url: str | None = None,
        vault_token: str | None = None,
        vault_mount_point: str | None = None,
    ) -> SecretStorePort:
        """Resolves the configured secret store adapter conforming to SecretStorePort.

        Reads configuration from SECRETS_BACKEND and SECRETS_MOUNT_PATH if not explicitly provided.
        """
        mount_path: str = (
            secrets_mount_path or os.getenv("SECRETS_MOUNT_PATH") or DEFAULT_SECRETS_MOUNT_PATH
        )
        raw_backend = backend or os.getenv("SECRETS_BACKEND", SecretStoreBackend.AWS)
        try:
            selected_backend = (
                raw_backend
                if isinstance(raw_backend, SecretStoreBackend)
                else SecretStoreBackend(str(raw_backend).strip().lower())
            )
        except ValueError:
            raise ValueError(
                f"Unsupported SECRETS_BACKEND '{raw_backend}'. "
                f"Supported backends: {[b.value for b in SecretStoreBackend]}"
            )

        resolver = path_resolver or MountedSecretPathResolver()
        if selected_backend in cls._secret_store_registry:
            logger.info(
                "secret_store_initialized",
                backend=selected_backend.value,
                mount_path=mount_path,
                registered_override=True,
            )
            return cls._secret_store_registry[selected_backend](
                secrets_mount_path=mount_path,
                path_resolver=resolver,
                endpoint_url=endpoint_url,
                region_name=region_name,
                client=client,
                aws_access_key_id=aws_access_key_id,
                aws_secret_access_key=aws_secret_access_key,
                secrets_prefix=secrets_prefix,
                aws_settings=aws_settings,
                vault_url=vault_url,
                vault_token=vault_token,
                vault_mount_point=vault_mount_point,
            )

        match selected_backend:
            case SecretStoreBackend.FILE | SecretStoreBackend.KUBERNETES:
                logger.info(
                    "secret_store_initialized",
                    backend=selected_backend.value,
                    mount_path=mount_path,
                    has_prefix=bool(secrets_prefix),
                )
                return FileSystemSecretStoreAdapter(
                    secrets_mount_path=mount_path,
                    secrets_prefix=secrets_prefix,
                    path_resolver=resolver,
                )
            case SecretStoreBackend.VAULT:
                logger.info(
                    "secret_store_initialized",
                    backend=selected_backend.value,
                    mount_path=mount_path,
                    vault_url=vault_url or "",
                    has_prefix=bool(secrets_prefix),
                )
                return VaultSecretStoreAdapter(
                    vault_url=vault_url,
                    vault_token=vault_token,
                    mount_point=vault_mount_point or DEFAULT_VAULT_MOUNT_POINT,
                    secrets_mount_path=mount_path,
                    secrets_prefix=secrets_prefix,
                    path_resolver=resolver,
                )
            case SecretStoreBackend.AWS:
                logger.info(
                    "secret_store_initialized",
                    backend=selected_backend.value,
                    mount_path=mount_path,
                    has_prefix=bool(secrets_prefix),
                )
                return AwsSecretsManagerAdapter(
                    endpoint_url=endpoint_url,
                    region_name=region_name,
                    secrets_mount_path=mount_path,
                    client=client,
                    aws_access_key_id=aws_access_key_id,
                    aws_secret_access_key=aws_secret_access_key,
                    secrets_prefix=secrets_prefix,
                    path_resolver=resolver,
                    aws_settings=aws_settings,
                )
            case SecretStoreBackend.GCP | SecretStoreBackend.AZURE:
                raise NotImplementedError(
                    f"Secret store backend '{selected_backend.value}' is architecturally supported "
                    f"via SecretStorePort, but its concrete adapter is not yet implemented. "
                    f"Implement the adapter and register it via SecretStoreProvider.register_secret_store_backend."
                )
