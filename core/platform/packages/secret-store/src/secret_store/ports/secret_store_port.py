"""Port protocol for external secrets management (Vault / AWS Secrets Manager)."""

from typing import Protocol, TypeAlias

Category: TypeAlias = str


def normalize_prefixed_category_ref(
    vault_ref: str,
    *,
    category: Category,
    secrets_prefix: str = "",
) -> str | None:
    """Validate and normalize a secret reference against ``[<secrets_prefix>/]<category>/<id>``."""
    clean_category = category.strip("/")
    if not clean_category or "/" in clean_category:
        return None

    clean_prefix = secrets_prefix.strip("/")
    expected_prefix = f"{clean_prefix}/{clean_category}/" if clean_prefix else f"{clean_category}/"
    normalized_ref = vault_ref.strip().removeprefix("vault://").strip("/")
    if not normalized_ref.startswith(expected_prefix):
        return None

    secret_leaf = normalized_ref.removeprefix(expected_prefix)
    if not secret_leaf or "/" in secret_leaf or secret_leaf in {".", ".."} or "\x00" in secret_leaf:
        return None
    return normalized_ref


class SecretStorePort(Protocol):
    """Hexagonal outbound port for retrieving and storing external secrets/certificates."""

    def normalize_category_ref(self, vault_ref: str, category: Category) -> str | None:
        """Return canonical secret ref if ``vault_ref`` belongs to ``category`` under this store's prefix."""
        ...

    async def get_secret(self, vault_ref: str) -> str:
        """Fetch a secret string given its reference path."""
        ...

    async def store_private_key(
        self, private_key_pem: bytes, category: Category | None = None
    ) -> str:
        """Stores a private key in the vault and returns its reference path."""
        ...

    async def retrieve_secret(self, vault_ref: str) -> bytes:
        """Retrieves any secret (private key, certificate, or credential) from vault."""
        ...

    async def retrieve_private_key(self, vault_ref: str) -> bytes:
        """Retrieves a private key from vault."""
        ...

    async def delete_secret(self, vault_ref: str) -> None:
        """Deletes a secret reference from vault."""
        ...
