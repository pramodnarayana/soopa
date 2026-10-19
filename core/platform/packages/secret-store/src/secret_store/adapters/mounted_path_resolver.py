"""Resolver for mounted secret volume paths."""

from pathlib import Path

import structlog

from secret_store.ports.secret_path_resolver_port import MountedSecretPathResolverPort

logger = structlog.get_logger(__name__)


class MountedSecretPathResolver(MountedSecretPathResolverPort):
    """Deterministic path resolver enforcing strict CWE-22 directory traversal prevention."""

    def resolve(self, mount_root: Path, vault_ref: str) -> Path | None:
        try:
            clean_ref = vault_ref.lstrip("/\\").replace("\\", "/")
            if not clean_ref:
                return None
            candidate = (mount_root / clean_ref).resolve()
            if candidate.is_relative_to(mount_root):
                return candidate
            logger.warning(
                "secrets_mount_path_traversal_prevented",
                vault_ref=vault_ref,
                candidate=str(candidate),
                mount_root=str(mount_root),
            )
            return None
        except (ValueError, OSError, RuntimeError):
            return None
