"""Unit tests for IngestRecordUseCase."""

from __future__ import annotations

from collections.abc import Sequence

import pytest
from ip.adapters.outbound.storage.tiered_storage_adapter import TieredStorageAdapter
from ip.application.ingress.ingest_record_use_case import (
    IngestRecordCommand,
    IngestRecordUseCase,
)
from ip.domain.models.inbound_record import InboundRecord
from ip.ports.outbound.inbound_record_repository_port import InboundRecordRepositoryPort


class InMemoryInboundRecordRepository(InboundRecordRepositoryPort):
    def __init__(self) -> None:
        self.records: dict[str, InboundRecord] = {}

    async def save(self, record: InboundRecord) -> None:
        self.records[record.id] = record

    async def get_by_id(self, record_id: str, tenant_id: str) -> InboundRecord | None:
        rec = self.records.get(record_id)
        if rec and rec.tenant_id == tenant_id:
            return rec
        return None

    async def get_by_trace_id(
        self, business_trace_id: str, tenant_id: str
    ) -> Sequence[InboundRecord]:
        return [
            r
            for r in self.records.values()
            if r.business_trace_id == business_trace_id and r.tenant_id == tenant_id
        ]


@pytest.mark.asyncio
async def test_ingest_record_inline() -> None:
    repo = InMemoryInboundRecordRepository()
    tiered_storage = TieredStorageAdapter(threshold_bytes=64 * 1024)
    use_case = IngestRecordUseCase(inbound_repo=repo, tiered_storage=tiered_storage)

    command = IngestRecordCommand(
        tenant_id="ten_energy_1",
        connection_id="ip_conn_itron_01",
        stream_name="meter_readings",
        payload={"meter": "MTR-9001", "kwh": 128.4},
        headers={"x-vendor": "itron"},
        business_correlation_id="TXN-4040",
    )

    result = await use_case.execute(command)

    assert result.status == "ACCEPTED"
    assert result.record_id.startswith("ip_inb_")
    assert result.business_trace_id.startswith("ip_trc_")
    assert result.is_inlined is True
    assert result.payload_size_bytes > 0

    # Verify repository saved aggregate
    saved = await repo.get_by_id(result.record_id, "ten_energy_1")
    assert saved is not None
    assert saved.business_correlation_id == "TXN-4040"
    assert saved.raw_payload == {"meter": "MTR-9001", "kwh": 128.4}
    assert saved.stream_name == "meter_readings"


@pytest.mark.asyncio
async def test_ingest_record_s3_offload() -> None:
    repo = InMemoryInboundRecordRepository()
    tiered_storage = TieredStorageAdapter(threshold_bytes=500)
    use_case = IngestRecordUseCase(inbound_repo=repo, tiered_storage=tiered_storage)

    large_dict = {"batch": ["item_" + str(i) for i in range(200)]}

    command = IngestRecordCommand(
        tenant_id="ten_crm_2",
        connection_id="ip_conn_sf_01",
        stream_name="bulk_contacts",
        payload=large_dict,
        business_correlation_id="BATCH-001",
    )

    result = await use_case.execute(command)

    assert result.status == "ACCEPTED"
    assert result.is_inlined is False
    assert result.payload_size_bytes > 500

    saved = await repo.get_by_id(result.record_id, "ten_crm_2")
    assert saved is not None
    assert saved.raw_payload is None
    assert saved.s3_key is not None
    assert saved.s3_key.startswith("s3://ip-payloads/ten_crm_2/")
