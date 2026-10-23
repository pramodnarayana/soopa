"""Narrow integration tests for TieredStorageAdapter against local LocalStack S3 (localhost:4566)."""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator

import aioboto3
import pytest
import pytest_asyncio
from ip.engine.adapters.outbound.storage.tiered_storage_adapter import (
    DEFAULT_IP_PAYLOAD_BUCKET,
    TieredStorageAdapter,
)
from ip.engine.domain.exceptions import PayloadNotFoundError
from ip.engine.ports.outbound.tiered_storage_port import TieredStorageResultDTO
from seedwork import generate_id
from seedwork.id_registry import DomainIdPrefix
from storage.adapters.s3_storage_adapter import Aioboto3PayloadStorage

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def s3_bucket() -> AsyncGenerator[str, None]:
    bucket_name = f"ip-test-{generate_id(DomainIdPrefix.TENANT.value).replace('_', '-')}"
    endpoint_url = os.environ.get("AWS_ENDPOINT_URL", "http://localhost:4566")
    session = aioboto3.Session()
    async with session.client(
        "s3",
        region_name="us-east-1",
        endpoint_url=endpoint_url,
        aws_access_key_id="test",
        aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY", "test"),
    ) as s3:
        await s3.create_bucket(Bucket=bucket_name)
        await s3.create_bucket(Bucket=DEFAULT_IP_PAYLOAD_BUCKET)
        yield bucket_name
        response = await s3.list_objects_v2(Bucket=bucket_name)
        if "Contents" in response:
            for obj in response["Contents"]:
                await s3.delete_object(Bucket=bucket_name, Key=obj["Key"])
        await s3.delete_bucket(Bucket=bucket_name)


@pytest.mark.asyncio
async def test_tiered_storage_offload_over_threshold_with_real_s3(s3_bucket: str) -> None:
    endpoint_url = os.environ.get("AWS_ENDPOINT_URL", "http://localhost:4566")
    real_s3_storage = Aioboto3PayloadStorage(
        bucket=s3_bucket,
        region="us-east-1",
        endpoint_url=endpoint_url,
        access_key_id="test",
        secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY", "test"),
    )

    adapter = TieredStorageAdapter(
        storage_client=real_s3_storage,
        threshold_bytes=1000,
    )

    large_bytes = b"A" * 2000
    result = await adapter.store(
        tenant_id="ten_999",
        trace_id="trc_large",
        payload_bytes=large_bytes,
    )

    expected_uri = (
        f"s3://{s3_bucket}/tenants/ten_999/inbound/trc_large_{result.payload_sha256[:16]}.bin"
    )
    assert result.is_inlined is False
    assert result.raw_payload is None
    assert result.s3_key == expected_uri
    assert result.payload_size_bytes == 2000

    retrieved_res = await adapter.retrieve(result)
    assert retrieved_res.is_ok is True
    assert retrieved_res.value == large_bytes


@pytest.mark.asyncio
async def test_tiered_storage_retrieve_missing_s3_key_returns_typed_error(s3_bucket: str) -> None:
    endpoint_url = os.environ.get("AWS_ENDPOINT_URL", "http://localhost:4566")
    real_s3_storage = Aioboto3PayloadStorage(
        bucket=s3_bucket,
        region="us-east-1",
        endpoint_url=endpoint_url,
        access_key_id="test",
        secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY", "test"),
    )
    adapter = TieredStorageAdapter(storage_client=real_s3_storage, threshold_bytes=500)
    missing_dto = TieredStorageResultDTO(
        is_inlined=False,
        raw_payload=None,
        s3_key=f"s3://{s3_bucket}/tenants/ten_999/inbound/does_not_exist.bin",
        payload_size_bytes=1024,
        payload_sha256="a" * 64,
    )
    res = await adapter.retrieve(missing_dto)
    assert res.is_err is True
    assert isinstance(res.error, PayloadNotFoundError)
