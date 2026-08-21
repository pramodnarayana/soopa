from typing import Protocol


class StoragePort(Protocol):
    """
    Interface for interacting with blob storage (e.g. S3).
    """

    async def download(self, uri: str) -> bytes:
        """Downloads the payload as bytes from the given URI."""
        ...

    async def upload(self, payload: bytes, key_prefix: str, file_name: str) -> str:
        """Uploads the payload to storage and returns the new URI."""
        ...
