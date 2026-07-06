from typing import Protocol


class VaultPort(Protocol):
    def store_private_key(self, private_key_pem: bytes, alias_prefix: str = "as2_key") -> str:
        """
        Stores a private key in Vault and returns the Vault reference path.
        """
        ...

    def retrieve_private_key(self, vault_ref: str) -> bytes:
        """
        Retrieves a private key from Vault.
        """
        ...

    def delete_secret(self, vault_ref: str) -> None:
        """
        Deletes a secret from Vault.
        """
        ...
