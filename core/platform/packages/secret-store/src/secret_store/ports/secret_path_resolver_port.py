"""Port defining mounted secret path resolution."""

from pathlib import Path
from typing import Protocol


class MountedSecretPathResolverPort(Protocol):
    """Protocol for resolving a vault secret reference to a candidate mounted file path."""

    def resolve(self, mount_root: Path, vault_ref: str) -> Path | None:
        """Resolves a vault reference into a path within mount_root, or None if invalid or escaping."""
        ...
