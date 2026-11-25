"""Narrow integration tests for IngestRecordUseCase using real PostgreSQL SAVEPOINTs and FileSystemPayloadStorage.

Zero mocks, zero InMemory/Fake classes: Tests L1 Ingestion Gateway against SqlAlchemyInboundRecordRepository
and TieredStorageAdapter backed by real FileSystemPayloadStorage on local disk.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from database.types import TenantSession
from identity.domain.constants import IdentityIdPrefix
from ip.engine.adapters.outbound.database.data_plane.inbound_record_repository import (
    SqlAlchemyInboundRecordRepository,
)
from ip.engine.adapters.outbound.storage.tiered_storage_adapter import TieredStorageAdapter
from ip.engine.application.use_cases.ingress.ingest_record_use_case import (
    IngestRecordCommand,
    IngestRecordUseCase,
)
from ip.engine.bootstrap.container import create_ip_data_plane_uow
from ip.engine.domain.constants import IpIdPrefix
from ip.engine.ports.outbound.tiered_storage_port import TieredStorageResultDTO
from seedwork import generate_id
from seedwork.domain.types import JsonDict
from storage.adapters.file_system_storage_adapter import FileSystemPayloadStorage

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_ingest_record_inline(tenant_session: TenantSession, tmp_path: Path) -> None:
    uow = create_ip_data_plane_uow(tenant_session)
    repo = SqlAlchemyInboundRecordRepository(tenant_session)
    storage = FileSystemPayloadStorage(base_directory=tmp_path)
    tiered_storage = TieredStorageAdapter(storage_client=storage, threshold_bytes=64 * 1024)
    use_case = IngestRecordUseCase(uow=uow, tiered_storage=tiered_storage)
    tenant_id = generate_id(IdentityIdPrefix.TENANT.value)
    connection_id = generate_id(IpIdPrefix.CONNECTION.value)

    command = IngestRecordCommand(
        tenant_id=tenant_id,
        connection_id=connection_id,
        stream_name="records_alpha",
        payload={"record_id": "REC-9001", "quantity": 128.4},
        headers={"x-vendor": "acme"},
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
    assert saved.request_body["record_id"] == "REC-9001"
    assert saved.request_body["quantity"] == 128.4
    assert "__raw_payload_b64__" in saved.request_body
    assert saved.stream_name == "records_alpha"


@pytest.mark.asyncio
async def test_ingest_record_storage_offload(
    tenant_session: TenantSession,
    tmp_path: Path,
) -> None:
    storage = FileSystemPayloadStorage(base_directory=tmp_path)
    uow = create_ip_data_plane_uow(tenant_session)
    repo = SqlAlchemyInboundRecordRepository(tenant_session)
    tiered_storage = TieredStorageAdapter(storage_client=storage, threshold_bytes=500)
    use_case = IngestRecordUseCase(uow=uow, tiered_storage=tiered_storage)
    tenant_id = generate_id(IdentityIdPrefix.TENANT.value)
    connection_id = generate_id(IpIdPrefix.CONNECTION.value)

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
    assert saved.request_s3_key.startswith("file://")

    retrieved = await tiered_storage.retrieve(
        TieredStorageResultDTO(
            is_inlined=False,
            raw_payload=None,
            s3_key=saved.request_s3_key,
            payload_size_bytes=result.payload_size_bytes,
            payload_sha256=saved.request_sha256,
        )
    )
    assert retrieved.is_ok is True
    assert json.loads(retrieved.value.decode("utf-8")) == large_dict
