"""Port protocol for external secrets management (Vault / AWS Secrets Manager)."""

from typing import Protocol, TypeAlias

Category: TypeAlias = str


class SecretStorePort(Protocol):
    """Hexagonal outbound port for retrieving and storing external secrets/certificates."""

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
