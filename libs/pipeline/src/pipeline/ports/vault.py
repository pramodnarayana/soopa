from typing import Protocol


class VaultPort(Protocol):
    async def get_secret(self, vault_ref: str) -> str:
        """Fetch a secret string from Vault given its reference."""
        ...
