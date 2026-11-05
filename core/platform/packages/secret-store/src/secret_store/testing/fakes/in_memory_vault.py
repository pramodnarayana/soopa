"""In-memory test fake implementation of SecretStorePort."""

from seedwork.id_registry import SystemIdPrefix
from seedwork.utils import generate_id

from secret_store.ports.secret_store_port import (
    Category,
    SecretStorePort,
    normalize_prefixed_category_ref,
)


class InMemoryVaultAdapter(SecretStorePort):
    """In-memory vault for testing without AWS Secrets Manager or LocalStack dependencies."""

    def __init__(self, secrets_prefix: str = "") -> None:
        self.secrets: dict[str, bytes] = {}
        self._secrets_prefix = secrets_prefix.strip("/")

    def normalize_category_ref(self, vault_ref: str, category: Category) -> str | None:
        return normalize_prefixed_category_ref(
            vault_ref,
            category=category,
            secrets_prefix=self._secrets_prefix,
        )

    async def get_secret(self, vault_ref: str) -> str:
        b = await self.retrieve_secret(vault_ref)
        return b.decode("utf-8")

    async def store_private_key(self, private_key_pem: bytes, category: str | None = None) -> str:
        secret_id = generate_id(SystemIdPrefix.GENERIC)
        cat = category if category else "keys"
        prefix = f"{self._secrets_prefix}/" if self._secrets_prefix else ""
        ref = f"{prefix}{cat}/{secret_id}"
        self.secrets[ref] = private_key_pem
        return ref

    async def retrieve_secret(self, vault_ref: str) -> bytes:
        if vault_ref not in self.secrets:
            raise ValueError(f"Secret not found in in-memory vault: {vault_ref}")
        return self.secrets[vault_ref]

    async def retrieve_private_key(self, vault_ref: str) -> bytes:
        return await self.retrieve_secret(vault_ref)

    async def delete_secret(self, vault_ref: str) -> None:
        self.secrets.pop(vault_ref, None)
