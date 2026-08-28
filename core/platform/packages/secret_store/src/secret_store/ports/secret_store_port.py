from typing import Protocol, TypeAlias

Category: TypeAlias = str


class SecretStorePort(Protocol):
    async def get_secret(self, vault_ref: str) -> str:
        """Fetch a secret string from Vault given its reference."""
        ...

    async def store_private_key(
        self, private_key_pem: bytes, category: Category | None = None
    ) -> str:
        """
        Stores a private key in Vault and returns the Vault reference path.
        """
        ...

    async def retrieve_secret(self, vault_ref: str) -> bytes:
        """
        Retrieves any secret (private key, certificate, or credential) from Vault.
        The semantically correct method for generic secret retrieval — use this
        instead of retrieve_private_key() when fetching public certificates.
        """
        ...

    async def retrieve_private_key(self, vault_ref: str) -> bytes:
        """
        Retrieves a private key from Vault.
        Delegates to retrieve_secret() — kept for backward compatibility.
        """
        ...

    async def delete_secret(self, vault_ref: str) -> None: ...
