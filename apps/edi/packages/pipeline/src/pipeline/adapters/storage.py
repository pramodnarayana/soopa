import aioboto3  # type: ignore[import-untyped]

from pipeline.ports.storage import StoragePort


class S3StorageAdapter(StoragePort):
    """
    Concrete implementation of StoragePort using AWS S3 (via aioboto3).
    """

    def __init__(
        self, bucket_name: str, endpoint_url: str | None = None, region: str = "us-east-1"
    ):
        self.bucket_name = bucket_name
        self.endpoint_url = endpoint_url
        self.region = region
        self.session = aioboto3.Session()

    async def _get_client_kwargs(self) -> dict[str, str]:
        kwargs = {"region_name": self.region}
        if self.endpoint_url:
            kwargs["endpoint_url"] = self.endpoint_url
        return kwargs

    async def download(self, uri: str) -> bytes:
        if not uri.startswith(f"s3://{self.bucket_name}/"):
            raise ValueError(f"URI must start with s3://{self.bucket_name}/")

        key = uri[len(f"s3://{self.bucket_name}/") :]
        kwargs = await self._get_client_kwargs()

        async with self.session.client("s3", **kwargs) as s3:
            response = await s3.get_object(Bucket=self.bucket_name, Key=key)
            return bytes(await response["Body"].read())

    async def upload(self, payload: bytes, key_prefix: str, file_name: str) -> str:
        key = f"{key_prefix.strip('/')}/{file_name}"
        kwargs = await self._get_client_kwargs()

        async with self.session.client("s3", **kwargs) as s3:
            await s3.put_object(Bucket=self.bucket_name, Key=key, Body=payload)

        return f"s3://{self.bucket_name}/{key}"
