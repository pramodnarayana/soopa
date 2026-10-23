"""Narrow integration tests for IngestRecordUseCase using real PostgreSQL SAVEPOINTs and LocalStack S3.

Zero mocks, zero InMemory/Fake classes: Tests L1 Ingestion Gateway against SqlAlchemyInboundRecordRepository
and TieredStorageAdapter backed by real LocalStack S3 (Aioboto3PayloadStorage).
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator

import aioboto3
import pytest
import pytest_asyncio
from database.types import TenantSession
from ip.engine.adapters.outbound.database.data_plane.inbound_record_repository import (
    SqlAlchemyInboundRecordRepository,
)
from ip.engine.adapters.outbound.database.data_plane.uow import (
    SqlAlchemyIpDataPlaneUnitOfWork,
)
from ip.engine.adapters.outbound.storage.tiered_storage_adapter import TieredStorageAdapter
from ip.engine.application.use_cases.ingress.ingest_record_use_case import (
    IngestRecordCommand,
    IngestRecordUseCase,
)
from seedwork import generate_id
from seedwork.domain.types import JsonDict
from seedwork.id_registry import DomainIdPrefix
from storage.adapters.s3_storage_adapter import Aioboto3PayloadStorage

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def s3_bucket() -> AsyncGenerator[str, None]:
    bucket_name = f"ip-ingest-{generate_id(DomainIdPrefix.TENANT.value).replace('_', '-')}"
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
        yield bucket_name
        response = await s3.list_objects_v2(Bucket=bucket_name)
        if "Contents" in response:
            for obj in response["Contents"]:
                await s3.delete_object(Bucket=bucket_name, Key=obj["Key"])
        await s3.delete_bucket(Bucket=bucket_name)


@pytest.mark.asyncio
async def test_ingest_record_inline(tenant_session: TenantSession) -> None:
    uow = SqlAlchemyIpDataPlaneUnitOfWork(tenant_session)
    repo = SqlAlchemyInboundRecordRepository(tenant_session)
    tiered_storage = TieredStorageAdapter(threshold_bytes=64 * 1024)
    use_case = IngestRecordUseCase(uow=uow, tiered_storage=tiered_storage)
    tenant_id = generate_id(DomainIdPrefix.TENANT.value)
    connection_id = generate_id(DomainIdPrefix.IP_CONNECTION.value)

    command = IngestRecordCommand(
        tenant_id=tenant_id,
        connection_id=connection_id,
        stream_name="meter_readings",
        payload={"meter": "MTR-9001", "kwh": 128.4},
        headers={"x-vendor": "itron"},
        correlation_id="TXN-4040",
    )

    result = await use_case.execute(command)

    assert result.status == "ACCEPTED"
    assert result.record_id.startswith("ip_inb_")
    assert result.trace_id.startswith("ip_trc_")
    assert result.is_inlined is True
    assert result.payload_size_bytes > 0

    saved = await repo.get_by_id(result.record_id, tenant_id)
    assert saved is not None
    assert saved.correlation_id == "TXN-4040"
    assert saved.request_body is not None
    assert saved.request_body["meter"] == "MTR-9001"
    assert saved.request_body["kwh"] == 128.4
    assert "__raw_payload_b64__" in saved.request_body
    assert saved.stream_name == "meter_readings"


@pytest.mark.asyncio
async def test_ingest_record_s3_offload(
    tenant_session: TenantSession,
    s3_bucket: str,
) -> None:
    endpoint_url = os.environ.get("AWS_ENDPOINT_URL", "http://localhost:4566")
    s3_storage = Aioboto3PayloadStorage(
        bucket=s3_bucket,
        region="us-east-1",
        endpoint_url=endpoint_url,
        access_key_id="test",
        secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY", "test"),
    )
    uow = SqlAlchemyIpDataPlaneUnitOfWork(tenant_session)
    repo = SqlAlchemyInboundRecordRepository(tenant_session)
    tiered_storage = TieredStorageAdapter(storage_client=s3_storage, threshold_bytes=500)
    use_case = IngestRecordUseCase(uow=uow, tiered_storage=tiered_storage)
    tenant_id = generate_id(DomainIdPrefix.TENANT.value)
    connection_id = generate_id(DomainIdPrefix.IP_CONNECTION.value)

    large_dict: JsonDict = {"batch": [f"item_{i}" for i in range(200)]}

    command = IngestRecordCommand(
        tenant_id=tenant_id,
        connection_id=connection_id,
        stream_name="bulk_contacts",
        payload=large_dict,
        correlation_id="BATCH-001",
    )

    result = await use_case.execute(command)

    assert result.status == "ACCEPTED"
    assert result.is_inlined is False
    assert result.payload_size_bytes > 500

    saved = await repo.get_by_id(result.record_id, tenant_id)
    assert saved is not None
    assert saved.request_body is None
    assert saved.request_s3_key is not None
    assert saved.request_s3_key.startswith(f"s3://{s3_bucket}/tenants/{tenant_id}/inbound/")
