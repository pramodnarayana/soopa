"""
Hexagonal Port and Adapter for S3 Payload Storage.
Business logic (FastAPI) depends only on the IPayloadStorage interface.
"""

from abc import ABC, abstractmethod

import aioboto3  # type: ignore[import-untyped]


class IPayloadStorage(ABC):
    """
    Port for storing massive AS2 payloads externally.
    """

    @abstractmethod
    async def upload(self, tenant_id: int, message_id: str, payload: bytes) -> str:
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


class Aioboto3PayloadStorage(IPayloadStorage):
    """
    Adapter implementing IPayloadStorage using aioboto3 (async AWS SDK).
    """

    def __init__(
        self,
        bucket: str,
        region: str,
        endpoint_url: str | None = None,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
    ):
        self.bucket = bucket
        self.region = region
        self.endpoint_url = endpoint_url
        self.access_key_id = access_key_id
        self.secret_access_key = secret_access_key

        self.session = aioboto3.Session()

    def _client_kwargs(self) -> dict[str, str]:
        kwargs = {"region_name": self.region}
        if self.endpoint_url:
            kwargs["endpoint_url"] = self.endpoint_url
        if self.access_key_id and self.secret_access_key:
            kwargs["aws_access_key_id"] = self.access_key_id
            kwargs["aws_secret_access_key"] = self.secret_access_key
        return kwargs

    async def upload(self, tenant_id: int, message_id: str, payload: bytes) -> str:
        key = f"tenants/{tenant_id}/inbound/{message_id}.bin"

        async with self.session.client("s3", **self._client_kwargs()) as s3:
            await s3.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=payload,
            )

        return f"s3://{self.bucket}/{key}"

    async def download(self, storage_uri: str) -> bytes | None:
        if not storage_uri.startswith(f"s3://{self.bucket}/"):
            return None

        key = storage_uri.replace(f"s3://{self.bucket}/", "")

        async with self.session.client("s3", **self._client_kwargs()) as s3:
            response = await s3.get_object(Bucket=self.bucket, Key=key)
            async with response["Body"] as stream:
                return bytes(await stream.read())

    async def generate_presigned_url(
        self,
        storage_uri: str,
        expiry_seconds: int = 3600,
        response_headers: dict[str, str] | None = None,
    ) -> str:
        if not storage_uri.startswith(f"s3://{self.bucket}/"):
            raise ValueError(f"storage_uri {storage_uri} does not belong to bucket {self.bucket}")

        key = storage_uri.replace(f"s3://{self.bucket}/", "")
        async with self.session.client("s3", **self._client_kwargs()) as s3:
            params = {
                "Bucket": self.bucket,
                "Key": key,
            }
            if response_headers and "Content-Disposition" in response_headers:
                params["ResponseContentDisposition"] = response_headers["Content-Disposition"]

            return str(
                await s3.generate_presigned_url(
                    "get_object",
                    Params=params,
                    ExpiresIn=expiry_seconds,
                )
            )
