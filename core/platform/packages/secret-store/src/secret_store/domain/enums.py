"""Secret store backend capability enums (core/platform/packages/secret-store)."""

from __future__ import annotations

from enum import StrEnum


class SecretStoreBackend(StrEnum):
    """Architecturally supported cloud and infrastructure backends for SecretStorePort."""

    AWS = "aws"
    VAULT = "vault"
    FILE = "file"
    KUBERNETES = "kubernetes"
    GCP = "gcp"
    AZURE = "azure"

    @property
    def requires_sync_sidecar(self) -> bool:
        """Whether this backend relies on an external secret-sync sidecar to populate local mounts."""
        return self in {
            SecretStoreBackend.AWS,
            SecretStoreBackend.GCP,
            SecretStoreBackend.AZURE,
        }
