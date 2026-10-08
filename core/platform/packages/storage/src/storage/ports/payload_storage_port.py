from abc import ABC, abstractmethod


class PayloadStoragePort(ABC):
    """
    Port for storing massive payloads externally.
    """

    @abstractmethod
    async def upload(self, tenant_id: str, message_id: str, payload: bytes) -> str:
        """
        Uploads the payload and returns the universal storage URI (e.g. s3://bucket/key).
        """
        ...

    @abstractmethod
    async def download(self, storage_uri: str) -> bytes | None:
        """
        Downloads a payload from the given storage URI.
        """
        ...

    @abstractmethod
    async def generate_presigned_url(
        self,
        storage_uri: str,
        expiry_seconds: int = 3600,
        response_headers: dict[str, str] | None = None,
    ) -> str:
        """
        Generates a presigned URL.
        """
        ...
