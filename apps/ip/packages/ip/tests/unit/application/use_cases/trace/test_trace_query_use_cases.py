"""Application use-case unit tests for GetIpTraceUseCase and GetIpTraceLineageUseCase."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest
from helpers.trace_fakes import InMemoryDataPlaneUoW, InMemoryDataPlaneUoWProvider
from ip.engine.application.responses import IpTraceLineageItemDTO
from ip.engine.application.use_cases.trace.get_ip_trace_lineage_use_case import (
    GetIpTraceLineageQuery,
    GetIpTraceLineageUseCase,
    ListRecentTracesQuery,
    SearchTracesByCorrelationQuery,
)
from ip.engine.application.use_cases.trace.get_ip_trace_use_case import (
    GetIpTraceQuery,
    GetIpTraceUseCase,
)
from ip.engine.domain.dispatch.enums import HttpWriteOperation, OutboundDispatchStatus
from ip.engine.domain.dispatch.outbound_record import OutboundRecord
from ip.engine.domain.enums import PipelineStage
from ip.engine.domain.exceptions import IpErrorCode
from ip.engine.domain.replication.enums import IngestionMode
from ip.engine.domain.replication.inbound_record import InboundRecord
from ip.engine.domain.trace import IpTraceStatus as TraceStatus


@pytest.mark.asyncio
async def test_get_ip_trace_use_case_returns_not_found_for_missing_trace() -> None:
    uow = InMemoryDataPlaneUoW()
    provider = InMemoryDataPlaneUoWProvider(uow)
    use_case = GetIpTraceUseCase(uow_provider=provider)

    missing_res = await use_case.execute(
        GetIpTraceQuery(tenant_id="ten_01", trace_id="ip_trc_missing")
    )
    assert missing_res.is_err
    assert missing_res.unwrap_err().code == IpErrorCode.TRACE_NOT_FOUND


@pytest.mark.asyncio
async def test_get_ip_trace_use_case_returns_waterfall_for_existing_trace() -> None:
    uow = InMemoryDataPlaneUoW()
    provider = InMemoryDataPlaneUoWProvider(uow)
    use_case = GetIpTraceUseCase(uow_provider=provider)

    inb = InboundRecord.create(
        tenant_id="ten_01",
        connection_id="conn_01",
        app_id="acme_source",
        stream_name="records_alpha",
        payload_bytes=b'{"record_id":"REC-100"}',
        is_inlined=True,
        trace_id="ip_trc_01",
        correlation_id="REC-100",
        ingestion_mode=IngestionMode.PUSH_FULL,
        request_body={"record_id": "REC-100"},
    )
    await uow.inbound_records.save(inb)

    ok_res = await use_case.execute(GetIpTraceQuery(tenant_id="ten_01", trace_id="ip_trc_01"))
    assert ok_res.is_ok
    trace_dto = ok_res.unwrap()
    assert trace_dto.trace_id == "ip_trc_01"
    assert trace_dto.correlation_id == "REC-100"
    assert trace_dto.inbound_record is not None
    assert trace_dto.inbound_record.id == inb.id


@pytest.mark.asyncio
async def test_get_ip_trace_lineage_returns_lineage_chain() -> None:
    uow = InMemoryDataPlaneUoW()
    now = datetime.now(UTC)
    uow.traces.lineage_items = [
        IpTraceLineageItemDTO(
            trace_id="ip_trc_root",
            correlation_id="REC-100",
            status=TraceStatus.FAILED,
            primary_layer=PipelineStage.DELIVER.value,
            created_at=now,
            replay_count=0,
            original_trace_id="ip_trc_root",
        ),
        IpTraceLineageItemDTO(
            trace_id="ip_trc_replay_1",
            correlation_id="REC-100",
            status=TraceStatus.DELIVERED,
            primary_layer=PipelineStage.DELIVER.value,
            created_at=now,
            replay_count=1,
            parent_trace_id="ip_trc_root",
            original_trace_id="ip_trc_root",
        ),
    ]
    provider = InMemoryDataPlaneUoWProvider(uow)
    use_case = GetIpTraceLineageUseCase(uow_provider=provider)

    lineage_res = await use_case.execute(
        GetIpTraceLineageQuery(tenant_id="ten_01", trace_id="ip_trc_replay_1")
    )
    assert lineage_res.is_ok
    assert len(lineage_res.unwrap()) == 2


@pytest.mark.asyncio
async def test_search_traces_by_correlation_returns_matching_items() -> None:
    uow = InMemoryDataPlaneUoW()
    now = datetime.now(UTC)
    uow.traces.lineage_items = [
        IpTraceLineageItemDTO(
            trace_id="ip_trc_root",
            correlation_id="REC-100",
            status=TraceStatus.FAILED,
            primary_layer=PipelineStage.DELIVER.value,
            created_at=now,
            replay_count=0,
            original_trace_id="ip_trc_root",
        ),
        IpTraceLineageItemDTO(
            trace_id="ip_trc_replay_1",
            correlation_id="REC-100",
            status=TraceStatus.DELIVERED,
            primary_layer=PipelineStage.DELIVER.value,
            created_at=now,
            replay_count=1,
            parent_trace_id="ip_trc_root",
            original_trace_id="ip_trc_root",
        ),
    ]
    provider = InMemoryDataPlaneUoWProvider(uow)
    use_case = GetIpTraceLineageUseCase(uow_provider=provider)

    corr_res = await use_case.search_by_correlation_id(
        SearchTracesByCorrelationQuery(tenant_id="ten_01", correlation_id="REC-100")
    )
    assert corr_res.is_ok
    assert len(corr_res.unwrap()) == 2


@pytest.mark.asyncio
async def test_list_recent_traces_orders_descending_by_created_at() -> None:
    uow = InMemoryDataPlaneUoW()
    tenant_id = f"ten_{os.urandom(12).hex()}"
    base_time = datetime(2026, 10, 29, 8, 0, tzinfo=UTC)

    newer_delivered = [
        IpTraceLineageItemDTO(
            trace_id=f"ip_trc_{os.urandom(12).hex()}",
            correlation_id=f"REC-{2000 + idx}",
            status=TraceStatus.DELIVERED,
            primary_layer=PipelineStage.DELIVER,
            created_at=base_time + timedelta(minutes=idx + 10),
            replay_count=0,
            parent_trace_id=None,
            original_trace_id=None,
        )
        for idx in range(5)
    ]
    uow.traces.lineage_items = list(newer_delivered)

    lineage_uc = GetIpTraceLineageUseCase(uow_provider=InMemoryDataPlaneUoWProvider(uow))
    all_res = await lineage_uc.list_recent(ListRecentTracesQuery(tenant_id=tenant_id, limit=3))
    assert all_res.is_ok
    assert [item.trace_id for item in all_res.unwrap()] == [
        newer_delivered[-1].trace_id,
        newer_delivered[-2].trace_id,
        newer_delivered[-3].trace_id,
    ]


@pytest.mark.asyncio
async def test_list_recent_traces_filters_by_status_with_minimum_replay_count() -> None:
    uow = InMemoryDataPlaneUoW()
    tenant_id = f"ten_{os.urandom(12).hex()}"
    root_trace_id = f"ip_trc_{os.urandom(12).hex()}"
    failed_replay_trace_id = f"ip_trc_{os.urandom(12).hex()}"
    base_time = datetime(2026, 10, 29, 8, 0, tzinfo=UTC)

    uow.traces.lineage_items = [
        IpTraceLineageItemDTO(
            trace_id=failed_replay_trace_id,
            correlation_id="REC-102",
            status=TraceStatus.FAILED,
            primary_layer=PipelineStage.DELIVER,
            created_at=base_time,
            replay_count=2,
            parent_trace_id=root_trace_id,
            original_trace_id=root_trace_id,
        ),
        IpTraceLineageItemDTO(
            trace_id=f"ip_trc_{os.urandom(12).hex()}",
            correlation_id="REC-200",
            status=TraceStatus.DELIVERED,
            primary_layer=PipelineStage.DELIVER,
            created_at=base_time + timedelta(minutes=10),
            replay_count=0,
            parent_trace_id=None,
            original_trace_id=None,
        ),
    ]

    lineage_uc = GetIpTraceLineageUseCase(uow_provider=InMemoryDataPlaneUoWProvider(uow))
    filtered_res = await lineage_uc.list_recent(
        ListRecentTracesQuery(
            tenant_id=tenant_id,
            status=TraceStatus.FAILED,
            min_replay_count=1,
            limit=10,
        )
    )
    assert filtered_res.is_ok
    assert [item.trace_id for item in filtered_res.unwrap()] == [failed_replay_trace_id]


@pytest.mark.asyncio
async def test_trace_lineage_queries_return_error_for_missing_tenant_shard() -> None:
    uow = InMemoryDataPlaneUoW()
    missing_tenant_id = f"ten_{os.urandom(12).hex()}"
    missing_trace_id = f"ip_trc_{os.urandom(12).hex()}"
    missing_uc = GetIpTraceLineageUseCase(
        uow_provider=InMemoryDataPlaneUoWProvider(uow, missing_tenant_ids={missing_tenant_id})
    )
    assert (
        await missing_uc.execute(
            GetIpTraceLineageQuery(tenant_id=missing_tenant_id, trace_id=missing_trace_id)
        )
    ).is_err
    assert (
        await missing_uc.search_by_correlation_id(
            SearchTracesByCorrelationQuery(tenant_id=missing_tenant_id, correlation_id="REC-1")
        )
    ).is_err
    assert (await missing_uc.list_recent(ListRecentTracesQuery(tenant_id=missing_tenant_id))).is_err


def test_derive_overall_status_maps_in_flight_outbound_record_to_pending() -> None:
    in_flight_record = OutboundRecord.create_pending(
        tenant_id="ten_01",
        trace_id="ip_trc_in_flight",
        connection_id="ip_conn_01",
        app_id="salesforce",
        stream_name="accounts",
        operation=HttpWriteOperation.UPSERT.value,
        target_url="https://api.example.com/accounts",
        http_method="POST",
        payload_bytes=b'{"name":"Acme"}',
        is_inlined=True,
        request_headers={},
        request_body={"name": "Acme"},
        status=OutboundDispatchStatus.IN_FLIGHT,
    )
    status = GetIpTraceUseCase.derive_overall_status(
        outbound_records=[in_flight_record],
        normalization_rejections=[],
        normalized_records=[],
        replica_rejections=[],
        replica_records=[],
        inbound_record=None,
    )
    assert status == TraceStatus.PENDING
