"""Narrow Integration Tests for SqlAlchemyTraceRepository and GetIpTraceUseCase against real PostgreSQL."""

from __future__ import annotations

import pytest
from database.types import TenantSession
from ip.engine.adapters.outbound.database.data_plane.uow import (
    SqlAlchemyIpDataPlaneUnitOfWork,
)
from ip.engine.application.use_cases.transactions.get_ip_trace_use_case import (
    GetIpTraceUseCase,
)
from ip.engine.domain.constants import REDACTED_SECRET_VALUE
from ip.engine.domain.enums import (
    HttpWriteOperation,
    IngestionMode,
    PipelineLayer,
)
from ip.engine.domain.exceptions import PayloadNotFoundError, Result
from ip.engine.domain.models.global_entity_map import GlobalEntityMap
from ip.engine.domain.models.inbound_record import InboundRecord
from ip.engine.domain.models.normalized_record import NormalizedRecord
from ip.engine.domain.models.outbound_record import OutboundRecord
from ip.engine.domain.models.replica_record import ReplicaRecord
from ip.engine.ports.outbound.tiered_storage_port import (
    TieredStoragePort,
    TieredStorageResultDTO,
)
from seedwork.domain.types import JsonValue
from strace.domain import TraceStatus

pytestmark = pytest.mark.integration


class InMemoryTieredStorageAdapter(TieredStoragePort):
    def __init__(self, blobs: dict[str, bytes]) -> None:
        self._blobs = blobs

    async def store(
        self,
        tenant_id: str,
        trace_id: str,
        payload_bytes: bytes,
        parsed_payload: JsonValue | None = None,
    ) -> TieredStorageResultDTO:
        _ = (tenant_id, trace_id, payload_bytes, parsed_payload)
        raise AssertionError("store not expected during trace read test")

    async def retrieve(self, result: TieredStorageResultDTO) -> Result[bytes, PayloadNotFoundError]:
        if result.s3_key and result.s3_key in self._blobs:
            return Result.ok(self._blobs[result.s3_key])
        return Result.err(PayloadNotFoundError(s3_key=result.s3_key, message="Missing S3 blob"))


@pytest.mark.asyncio
async def test_trace_repository_5_layer_waterfall_upstream_hydration_and_lineage(
    tenant_session: TenantSession,
) -> None:
    tenant_id = "ten_dp_trace_01"
    root_trace_id = "ip_trc_int_root_01"
    child_trace_id = "ip_trc_int_child_01"

    storage = InMemoryTieredStorageAdapter(
        {
            "s3://ip-payloads/ten_dp_trace_01/inb_01.json": b'{"meter_id":"MTR-500","kwh":88.2}',
        }
    )
    uow = SqlAlchemyIpDataPlaneUnitOfWork(tenant_session, storage=storage)

    # 1. Seed full 5-layer root trace (which fails at L5)
    inb = InboundRecord.create(
        tenant_id=tenant_id,
        connection_id="ip_conn_src_01",
        app_id="itron_mdm",
        stream_name="meter_reads",
        payload_bytes=b'{"meter_id":"MTR-500","kwh":88.2}',
        is_inlined=False,
        request_s3_key="s3://ip-payloads/ten_dp_trace_01/inb_01.json",
        trace_id=root_trace_id,
        correlation_id="MTR-500",
        ingestion_mode=IngestionMode.PUSH_FULL,
        request_headers={"Authorization": "Bearer top-secret"},
        request_body=None,
    )
    await uow.inbound_records.save(inb)

    rep = ReplicaRecord.create(
        tenant_id=tenant_id,
        connection_id="ip_conn_src_01",
        stream="meter_reads",
        primary_key_values=("MTR-500",),
        data={"meter_id": "MTR-500", "kwh": 88.2},
        source_inbound_record_id=inb.id,
        trace_id=root_trace_id,
        correlation_id="MTR-500",
    )
    await uow.replica_records.save(rep)

    nrm = NormalizedRecord.create(
        tenant_id=tenant_id,
        connection_id="ip_conn_src_01",
        canonical_type="mdm.meter_reading",
        source_id="MTR-500",
        canonical_data={"meter_id": "MTR-500", "reading_kwh": 88.2},
        trace_id=root_trace_id,
        correlation_id="MTR-500",
    )
    await uow.normalized_records.save(nrm)

    gem = GlobalEntityMap.create(
        tenant_id=tenant_id,
        entity_domain="mdm.meter_reading",
        canonical_id=nrm.id,
        source_connection_id="ip_conn_src_01",
        source_entity_id="MTR-500",
        dest_connection_id="ip_conn_dest_01",
        dest_entity_id="NS-INV-500",
        trace_id=root_trace_id,
        correlation_id="MTR-500",
    )
    await uow.entity_maps.save(gem)

    out_root = OutboundRecord.create_pending(
        tenant_id=tenant_id,
        connection_id="ip_conn_dest_01",
        app_id="netsuite_erp",
        stream_name="invoices",
        target_url="https://api.netsuite.example.com/v1/invoices",
        http_method="POST",
        payload_bytes=b'{"meter_id":"MTR-500"}',
        is_inlined=True,
        trace_id=root_trace_id,
        operation=HttpWriteOperation.CREATE.value,
        correlation_id="MTR-500",
        request_headers={"X-API-Key": "secret-key"},
        request_body={"meter_id": "MTR-500"},
    )
    out_root.mark_failed(error_message="HTTP 503 Unavailable", response_status_code=503)
    await uow.outbound_records.save(out_root)

    # 2. Seed an L5 delivery replay child trace (which only writes OutboundRecord)
    out_child = out_root.clone_for_delivery_retry(
        new_trace_id=child_trace_id,
        parent_trace_id=root_trace_id,
        original_trace_id=root_trace_id,
        replay_count=1,
        actor="ops@soopa.io",
    )
    out_child.mark_delivered(
        response_status_code=201,
        response_headers={"Content-Type": "application/json"},
        response_body={"id": "NS-INV-500"},
        duration_ms=85,
    )
    await uow.outbound_records.save(out_child)

    # 3. Verify GetIpTraceUseCase.assemble_in_uow hydrates upstream L1, L2, L3 from root_trace_id + S3 payload
    child_waterfall = await GetIpTraceUseCase.assemble_in_uow(
        uow,
        tenant_id=tenant_id,
        trace_id=child_trace_id,
        hydrate_payloads=True,
    )
    assert child_waterfall is not None
    assert child_waterfall.trace_id == child_trace_id
    assert child_waterfall.parent_trace_id == root_trace_id
    assert child_waterfall.original_trace_id == root_trace_id
    assert child_waterfall.replay_count == 1
    assert child_waterfall.status == TraceStatus.DELIVERED
    assert child_waterfall.inbound_record is not None
    assert child_waterfall.inbound_record.id == inb.id
    assert child_waterfall.inbound_record.request_headers["Authorization"] == REDACTED_SECRET_VALUE
    assert child_waterfall.inbound_record.request_body == {"meter_id": "MTR-500", "kwh": 88.2}
    assert len(child_waterfall.replica_records) == 1
    assert len(child_waterfall.normalized_records) == 1
    assert len(child_waterfall.outbound_records) == 1
    assert child_waterfall.outbound_records[0].id == out_child.id

    # 4. Verify uow.traces.get_trace_lineage returns both root and child attempts in order
    lineage = await uow.traces.get_trace_lineage(tenant_id, child_trace_id)
    assert len(lineage) == 2
    assert lineage[0].trace_id == root_trace_id
    assert lineage[0].status == TraceStatus.FAILED
    assert lineage[0].replay_count == 0
    assert lineage[1].trace_id == child_trace_id
    assert lineage[1].status == TraceStatus.DELIVERED
    assert lineage[1].replay_count == 1
    assert lineage[1].primary_layer == PipelineLayer.L5_DELIVER.value

    # 5. Verify uow.traces.find_traces_by_correlation_id
    corr_results = await uow.traces.find_traces_by_correlation_id(tenant_id, "MTR-500")
    assert len(corr_results) == 2
