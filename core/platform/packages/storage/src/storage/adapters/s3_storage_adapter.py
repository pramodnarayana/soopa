"""S3 and MinIO payload storage adapter using aioboto3."""

from __future__ import annotations

from collections.abc import AsyncIterable
from datetime import UTC, datetime

import aioboto3

from storage.codecs import StorageCodec
from storage.domain.enums import CompressionCodec
from storage.ports.payload_storage_port import PayloadStoragePort

MIN_MULTIPART_CHUNK_BYTES: int = 5 * 1024 * 1024  # 5MB S3 part size requirement


class Aioboto3PayloadStorage(PayloadStoragePort):
    """High-throughput S3 and MinIO storage adapter supporting streaming and partitioning."""

    def __init__(
        self,
        bucket: str,
        region: str,
        endpoint_url: str | None = None,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
    ) -> None:
        self.bucket = bucket
        self.region = region
        self.endpoint_url = endpoint_url
        self.access_key_id = access_key_id
        self.secret_access_key = secret_access_key

        self.session = aioboto3.Session()

    def _client_kwargs(self) -> dict[str, str]:
        kwargs: dict[str, str] = {"region_name": self.region}
        if self.endpoint_url:
            kwargs["endpoint_url"] = self.endpoint_url
        if self.access_key_id and self.secret_access_key:
            kwargs["aws_access_key_id"] = self.access_key_id
            kwargs["aws_secret_access_key"] = self.secret_access_key
        return kwargs

    def build_partitioned_key(
        self,
        tenant_id: str,
        stream_name: str,
        batch_id: str,
        extension: str = "raw",
        compression: CompressionCodec = CompressionCodec.NONE,
    ) -> str:
        date_str = datetime.now(UTC).strftime("%Y-%m-%d")
        ext = extension.lstrip(".")
        if compression != CompressionCodec.NONE and not ext.endswith(
            compression.file_extension.lstrip(".")
        ):
            ext = f"{ext}{compression.file_extension}"
        return f"tenants/{tenant_id}/{stream_name}/{date_str}/{batch_id}.{ext}"

    async def upload(self, tenant_id: str, message_id: str, payload: bytes) -> str:
        key = f"tenants/{tenant_id}/inbound/{message_id}.bin"
        async with self.session.client("s3", **self._client_kwargs()) as s3:
            await s3.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=payload,
            )
        return f"s3://{self.bucket}/{key}"

    async def upload_partitioned(
        self,
        tenant_id: str,
        stream_name: str,
        batch_id: str,
        payload: bytes,
        extension: str = "raw",
        compression: CompressionCodec = CompressionCodec.NONE,
    ) -> str:
        key = self.build_partitioned_key(
            tenant_id=tenant_id,
            stream_name=stream_name,
            batch_id=batch_id,
            extension=extension,
            compression=compression,
        )
        data = StorageCodec.compress(payload, compression)

        async with self.session.client("s3", **self._client_kwargs()) as s3:
            await s3.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=data,
            )
        return f"s3://{self.bucket}/{key}"

    async def upload_stream(
        self,
        tenant_id: str,
        stream_name: str,
        batch_id: str,
        stream: AsyncIterable[bytes],
        extension: str = "raw",
        compression: CompressionCodec = CompressionCodec.NONE,
        content_type: str = "application/octet-stream",
    ) -> str:
        key = self.build_partitioned_key(
            tenant_id=tenant_id,
            stream_name=stream_name,
            batch_id=batch_id,
            extension=extension,
            compression=compression,
        )

        async with self.session.client("s3", **self._client_kwargs()) as s3:
            # We compress the stream chunks
            compressed_stream = StorageCodec.compress_stream(stream, compression)
            buffer = bytearray()
            parts: list[dict[str, object]] = []
            part_number = 1

            mp_resp = await s3.create_multipart_upload(
                Bucket=self.bucket,
                Key=key,
                ContentType=content_type,
            )
            upload_id = str(mp_resp["UploadId"])

            try:
                async for chunk in compressed_stream:
                    buffer.extend(chunk)
                    while len(buffer) >= MIN_MULTIPART_CHUNK_BYTES:
                        part_bytes = bytes(buffer[:MIN_MULTIPART_CHUNK_BYTES])
                        del buffer[:MIN_MULTIPART_CHUNK_BYTES]

                        part_resp = await s3.upload_part(
                            Bucket=self.bucket,
                            Key=key,
                            PartNumber=part_number,
                            UploadId=upload_id,
                            Body=part_bytes,
                        )
                        parts.append({"PartNumber": part_number, "ETag": part_resp["ETag"]})
                        part_number += 1

                # Flush final part if remaining bytes exist or if no parts were uploaded yet
                if len(buffer) > 0 or not parts:
                    part_resp = await s3.upload_part(
                        Bucket=self.bucket,
                        Key=key,
                        PartNumber=part_number,
                        UploadId=upload_id,
                        Body=bytes(buffer),
                    )
                    parts.append({"PartNumber": part_number, "ETag": part_resp["ETag"]})

                await s3.complete_multipart_upload(
                    Bucket=self.bucket,
                    Key=key,
                    UploadId=upload_id,
                    MultipartUpload={"Parts": parts},
                )
            except Exception:
                await s3.abort_multipart_upload(
                    Bucket=self.bucket,
                    Key=key,
                    UploadId=upload_id,
                )
                raise

        return f"s3://{self.bucket}/{key}"

    async def download(self, storage_uri: str, decompress: bool = True) -> bytes | None:
        prefix = f"s3://{self.bucket}/"
        if not storage_uri.startswith(prefix):
            return None

        key = storage_uri.removeprefix(prefix)

        async with self.session.client("s3", **self._client_kwargs()) as s3:
            response = await s3.get_object(Bucket=self.bucket, Key=key)
            async with response["Body"] as stream:
                raw_bytes = bytes(await stream.read())

        if not decompress:
            return raw_bytes

        # Inspect extension for decompression
        if key.endswith(".gz"):
            return StorageCodec.decompress(raw_bytes, CompressionCodec.GZIP)
        if key.endswith(".zst"):
            return StorageCodec.decompress(raw_bytes, CompressionCodec.ZSTD)

        return raw_bytes

    async def download_stream(self, storage_uri: str) -> AsyncIterable[bytes]:
        prefix = f"s3://{self.bucket}/"
        if not storage_uri.startswith(prefix):
            return

        key = storage_uri.removeprefix(prefix)

        async with self.session.client("s3", **self._client_kwargs()) as s3:
            response = await s3.get_object(Bucket=self.bucket, Key=key)
            async with response["Body"] as stream:
                while True:
                    chunk = await stream.read(1024 * 1024)
                    if not chunk:
                        break
                    yield bytes(chunk)

    async def generate_presigned_url(
        self,
        storage_uri: str,
        expiry_seconds: int = 3600,
        response_headers: dict[str, str] | None = None,
    ) -> str:
        prefix = f"s3://{self.bucket}/"
        if not storage_uri.startswith(prefix):
            raise ValueError(f"storage_uri {storage_uri} does not belong to bucket {self.bucket}")

        key = storage_uri.removeprefix(prefix)
        async with self.session.client("s3", **self._client_kwargs()) as s3:
            params: dict[str, object] = {
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
